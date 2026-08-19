"""
main.py - Coima COMPR.AR scraper entry point.

Orchestrates the pipeline: read process numbers from the tenders file, search
each on comprar.gob.ar, scrape the detail page and all relevant sub-pages, and
ingest the result directly into Neo4j.

Resume support: completed process numbers are appended to
`output/progress.json` after each successful ingestion, so an interrupted run
skips already-done processes on restart. Use `--reset-progress` to start
fresh.

Run `python main.py --help` for full usage.
"""

from __future__ import annotations

import argparse
import json
import re
import pathlib
import signal
import sys
import unicodedata
from datetime import datetime

from tqdm import tqdm

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from config import settings
from ingestion.neo4j_client import Neo4jClient
from scraper.acta_page import ActaPageParser, ActaPageResult
from scraper.dictamen_page import DictamenPageParser, DictamenPageResult
from scraper.models import (
    AuthorizedByRelProps,
    AuthorizerModel,
    BidLineModel,
    BidModel,
    ContractLineModel,
    ContractualDocumentModel,
    DictamenModel,
    DictamenSignerModel,
    EvaluatedByRelProps,
    PreAdjudicatesRelProps,
    ProcessResult,
    ProviderModel,
    ProvisionRequestLineModel,
    ProvisionRequestModel,
    RejectedRelProps,
)
from scraper.oc_page import OCPageParser, OCPageResult
from scraper.offers_page import OffersPageParser
from scraper.process_page import ProcessPageParser
from scraper.search import ProcessFinder
from scraper.session import ScraperSession, decode_response
from scraper.spr_page import SPRPageParser, SPRPageResult
from utils.logging_config import get_logger, setup_logging
from utils.parsers import make_absolute, normalize_currency

logger = get_logger(__name__)


class ProgressTracker:
    """Persists successfully scraped process numbers so runs can resume.

    The file holds one process number per line (a legacy JSON array format is
    migrated to the line-based format on load).
    """

    def __init__(self, path: pathlib.Path) -> None:
        self._path = path
        self._completed: set[str] = set()
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                text = self._path.read_text(encoding="utf-8").strip()
                if not text:
                    self._completed = set()
                elif text.startswith("["):
                    # Legacy JSON format: parse and migrate to line-based.
                    data = json.loads(text)
                    self._completed = set(data) if isinstance(data, list) else set()
                    self._path.write_text(
                        "\n".join(sorted(self._completed)) + "\n",
                        encoding="utf-8",
                    )
                else:
                    self._completed = set(
                        line.strip() for line in text.splitlines() if line.strip()
                    )
                if self._completed:
                    logger.info(
                        "Resuming: %d processes already completed (loaded from %s).",
                        len(self._completed), self._path,
                    )
            except Exception as exc:
                logger.warning("Could not load progress file %s: %s. Starting fresh.", self._path, exc)
                self._completed = set()

    def is_done(self, process_number: str) -> bool:
        """Return True if the process number was already completed."""
        return process_number in self._completed

    def mark_done(self, process_number: str) -> None:
        """Record a process number as completed and append it to the file."""
        self._completed.add(process_number)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(process_number + "\n")

    def reset(self) -> None:
        """Clear in-memory and on-disk progress state."""
        self._completed = set()
        if self._path.exists():
            self._path.unlink()
        logger.info("Progress reset. All processes will be scraped from scratch.")

    @property
    def completed_count(self) -> int:
        return len(self._completed)


class ScrapeOrchestrator:
    """Runs the full scrape pipeline for a single process number.

    A fresh instance is created per process; the accumulated entities live as
    instance attributes and are packed into a :class:`ProcessResult` at the end.
    The flow follows the schema decision logic: search, parse the detail page,
    and parse the offers, OC, OCA, and SPR sub-pages.
    """

    def __init__(self, session: ScraperSession, process_number: str) -> None:
        self._session = session
        self._process_number = process_number
        self._detail_url: str | None = None
        self._page: ProcessPageParser | None = None  # actually a ProcessPageResult

        self._providers: list[ProviderModel] = []
        self._bids: list[BidModel] = []
        self._bid_lines: list[BidLineModel] = []
        self._contractual_documents: list[ContractualDocumentModel] = []
        self._contract_lines: list[ContractLineModel] = []
        self._authorizers: list[AuthorizerModel] = []
        self._authorizations_cd: list[tuple[str, AuthorizedByRelProps]] = []
        self._provision_requests: list[ProvisionRequestModel] = []
        self._provision_request_lines: list[ProvisionRequestLineModel] = []
        self._authorizations_spr: list[tuple[str, AuthorizedByRelProps]] = []
        self._dictamenes: list[DictamenModel] = []
        self._dictamen_signers: list[DictamenSignerModel] = []
        self._evaluations: list[EvaluatedByRelProps] = []
        self._pre_adjudications: list[PreAdjudicatesRelProps] = []
        self._rejections: list[RejectedRelProps] = []

    def scrape(self) -> ProcessResult | None:
        """Execute the pipeline and return a ProcessResult, or None on failure."""
        session = self._session
        process_number = self._process_number

        logger.info("=" * 60)
        logger.info("Processing: %s", process_number)
        logger.info("=" * 60)

        # Step 1: search for the process URL.
        try:
            detail_url, process_status = ProcessFinder(session).find(process_number)
        except Exception as exc:
            logger.error("Search failed for %s: %s", process_number, exc, exc_info=True)
            return None

        if not detail_url:
            logger.warning("Process not found: %s. Skipping.", process_number)
            return None
        self._detail_url = detail_url

        # Step 2: parse the process detail page.
        try:
            html = session.get(detail_url)
            page = ProcessPageParser(
                html, process_number, source_url=detail_url, override_status=process_status
            ).parse()
        except Exception as exc:
            logger.error("Failed to parse process page for %s: %s", process_number, exc, exc_info=True)
            return None
        self._page = page

        logger.info(
            "Process %s: status=%s, line_items=%d",
            process_number, page.process.status, len(page.line_items),
        )

        self._providers = list(page.invited_providers)

        # Step 4a: comparative offer table.
        if page.offers_target:
            try:
                html, offers_url = self._fetch_subpage(page.offers_target)
                page.process.offers_url = offers_url
                new_providers, new_bids, new_bid_lines = OffersPageParser(html, process_number).parse()
                self._add_providers(new_providers)
                self._bids.extend(new_bids)
                self._bid_lines.extend(new_bid_lines)
                logger.info(
                    "Process %s: bids=%d, bid_lines=%d",
                    process_number, len(new_bids), len(new_bid_lines),
                )
            except Exception as exc:
                logger.error("Offers page failed for %s: %s", process_number, exc, exc_info=True)

        # Step 4b: purchase orders (OC).
        for oc_target in page.oc_targets:
            try:
                html, oc_url = self._fetch_subpage(oc_target)
                oc_result = OCPageParser(html, process_number, source_url=oc_url, is_oca=False).parse()
                self._apply_contract_summary(oc_result, page.contract_summaries.get(oc_target))
                self._apply_oc(oc_result)
            except Exception as exc:
                logger.error("OC page target failed (%s) for %s: %s", oc_target, process_number, exc, exc_info=True)

        # Step 4c: open purchase order (OCA) and its SPR pages.
        if page.oca_target:
            try:
                html, oca_url = self._fetch_subpage(page.oca_target)
                oca_result = OCPageParser(html, process_number, source_url=oca_url, is_oca=True).parse()
                self._apply_contract_summary(oca_result, page.contract_summaries.get(page.oca_target))
                self._apply_oc(oca_result)

                oca_number = oca_result.document.document_number if oca_result.document else ""
                for spr_url in oca_result.spr_urls:
                    try:
                        html = session.get(spr_url, timeout=settings.spr_request_timeout)
                        spr = SPRPageParser(html, oca_number=oca_number, source_url=spr_url).parse()
                        self._apply_spr(spr)
                    except Exception as exc:
                        logger.error("SPR page failed (%s): %s", spr_url, exc, exc_info=True)
            except Exception as exc:
                logger.error("OCA page failed for %s: %s", process_number, exc, exc_info=True)

        # Step 4d (contratar): opening acts - real opening datetime plus
        # per-proposal guarantee data.
        for acta_target in page.opening_act_targets:
            try:
                html, _ = self._fetch_subpage(acta_target)
                self._apply_acta(ActaPageParser(html).parse())
            except Exception as exc:
                logger.error("Opening act failed (%s) for %s: %s", acta_target, process_number, exc, exc_info=True)

        # Step 4e (contratar): pre-award opinions - committee, recommended
        # winners per renglón, and discarded bidders with reasons.
        for sequence, dictamen_target in enumerate(page.dictamen_targets, start=1):
            try:
                html, dictamen_url = self._fetch_subpage(dictamen_target)
                self._apply_dictamen(DictamenPageParser(html).parse(), sequence, dictamen_url)
            except Exception as exc:
                logger.error("Dictamen failed (%s) for %s: %s", dictamen_target, process_number, exc, exc_info=True)

        logger.info(
            "Process %s DONE: bids=%d, contracts=%d, SPRs=%d, evaluators=%d",
            process_number, len(self._bids), len(self._contractual_documents),
            len(self._provision_requests), len(self._evaluations),
        )
        return self._build_result()

    def _fetch_subpage(self, target_id: str) -> tuple[str, str]:
        """Navigate to a sub-page by direct URL or ASP.NET postback target.

        Returns:
            A ``(html, resolved_url)`` tuple.
        """
        if (
            target_id.startswith("http")
            or target_id.startswith("/")
            or target_id.startswith("./")
            or ".aspx?" in target_id.lower()
        ):
            normalized_target = target_id[2:] if target_id.startswith("./") else target_id
            url = make_absolute(settings.base_url, normalized_target)
            return self._session.get(url), url

        post_data = {
            **self._page.viewstate_data,
            "__EVENTTARGET": target_id,
            "__EVENTARGUMENT": "",
        }
        response = self._session._session.post(
            self._detail_url, data=post_data,
            timeout=settings.request_timeout, allow_redirects=True,
        )
        response.raise_for_status()
        return decode_response(response), response.url

    @staticmethod
    def _apply_contract_summary(oc_result: OCPageResult, summary: dict | None) -> None:
        """Apply status/currency from the process-page adjudications table."""
        if not summary or oc_result.document is None:
            return
        if summary.get("status"):
            oc_result.document.status = summary["status"]
        if summary.get("currency"):
            oc_result.document.currency = normalize_currency(summary["currency"])

    def _add_providers(self, new_providers: list[ProviderModel]) -> None:
        """Add or enrich providers, merging null fields of existing records."""
        cuit_to_idx = {p.cuit: i for i, p in enumerate(self._providers)}
        for new_p in new_providers:
            if new_p.cuit not in cuit_to_idx:
                self._providers.append(new_p)
                cuit_to_idx[new_p.cuit] = len(self._providers) - 1
            else:
                existing = self._providers[cuit_to_idx[new_p.cuit]]
                if not existing.business_name and new_p.business_name:
                    existing.business_name = new_p.business_name
                if not existing.sipro_entity_id and new_p.sipro_entity_id:
                    existing.sipro_entity_id = new_p.sipro_entity_id
                if not existing.address and new_p.address:
                    existing.address = new_p.address
                if not existing.postal_code and new_p.postal_code:
                    existing.postal_code = new_p.postal_code
                if not existing.city and new_p.city:
                    existing.city = new_p.city
                if not existing.province and new_p.province:
                    existing.province = new_p.province
                if not existing.phone and new_p.phone:
                    existing.phone = new_p.phone
                if not existing.fax and new_p.fax:
                    existing.fax = new_p.fax
                if not existing.email and new_p.email:
                    existing.email = new_p.email
                if not existing.sipro_status and new_p.sipro_status:
                    existing.sipro_status = new_p.sipro_status

    def _apply_oc(self, oc: OCPageResult) -> None:
        """Merge an OC/OCA result into the accumulators."""
        page = self._page
        if oc.document:
            self._contractual_documents.append(oc.document)
        if oc.buyer:
            if page.organization is None:
                page.organization = oc.buyer
                if page.contracting_unit is not None:
                    page.contracting_unit.saf_code = oc.buyer.saf_code
            else:
                if page.organization.saf_code != oc.buyer.saf_code:
                    logger.warning(
                        "SAF mismatch on %s: process_page=%s, oc_page=%s. Using OC/OCA SAF.",
                        self._process_number, page.organization.saf_code, oc.buyer.saf_code,
                    )
                    page.organization.saf_code = oc.buyer.saf_code
                    if page.contracting_unit is not None:
                        page.contracting_unit.saf_code = oc.buyer.saf_code
                if not page.organization.name and oc.buyer.name:
                    page.organization.name = oc.buyer.name

            # In OCA, buyer contact belongs to the Organization (SAF).
            if oc.is_oca:
                if not page.organization.address and oc.buyer.address:
                    page.organization.address = oc.buyer.address
                if not page.organization.phone and oc.buyer.phone:
                    page.organization.phone = oc.buyer.phone
                if not page.organization.email and oc.buyer.email:
                    page.organization.email = oc.buyer.email
            # In OC, buyer contact data is modeled on the ContractingUnit.
            elif page.contracting_unit is not None:
                if not page.contracting_unit.address and oc.buyer_contact.get("address"):
                    page.contracting_unit.address = oc.buyer_contact["address"]
                if not page.contracting_unit.postal_code and oc.buyer_contact.get("postal_code"):
                    page.contracting_unit.postal_code = oc.buyer_contact["postal_code"]
                if not page.contracting_unit.province and oc.buyer_contact.get("province"):
                    page.contracting_unit.province = oc.buyer_contact["province"]
                if not page.contracting_unit.email and oc.buyer_contact.get("email"):
                    page.contracting_unit.email = oc.buyer_contact["email"]
        if oc.provider:
            self._add_providers([oc.provider])
        self._contract_lines.extend(oc.contract_lines)

        self._merge_authorizers(oc.authorizers)
        self._authorizations_cd.extend(oc.authorizations)

    def _apply_acta(self, acta: ActaPageResult) -> None:
        """Merge an opening act into the process and bid accumulators."""
        page = self._page
        if acta.opening_datetime and not page.process.opening_date:
            page.process.opening_date = acta.opening_datetime

        bid_by_cuit = {b.provider_cuit: b for b in self._bids}
        for prop in acta.proposals:
            self._add_providers([ProviderModel(cuit=prop.cuit, business_name=prop.business_name)])
            bid = bid_by_cuit.get(prop.cuit)
            if bid is None:
                bid = BidModel(process_number=self._process_number, provider_cuit=prop.cuit)
                self._bids.append(bid)
                bid_by_cuit[prop.cuit] = bid
            if bid.submitted_at is None:
                bid.submitted_at = prop.submitted_at
            if bid.total_amount is None:
                bid.total_amount = prop.total_amount
            if not bid.currency:
                bid.currency = prop.currency
            if not bid.guarantee_type:
                bid.guarantee_type = prop.guarantee_type
            if not bid.guarantee_form:
                bid.guarantee_form = prop.guarantee_form
            if bid.guarantee_amount is None:
                bid.guarantee_amount = prop.guarantee_amount

    def _apply_dictamen(self, dictamen: DictamenPageResult, sequence: int, source_url: str | None) -> None:
        """Merge a pre-award opinion into the dictamen/evaluation accumulators.

        Builds one Dictamen node per pre-award opinion, attaches its signers,
        recommended winners per renglón and discarded bidders, resolving the
        provider business names the grids expose to CUITs via the process's
        already-scraped providers.
        """
        page = self._page
        if dictamen.opening_datetime and not page.process.opening_date:
            page.process.opening_date = dictamen.opening_datetime

        self._dictamenes.append(DictamenModel(
            process_number=self._process_number,
            sequence=sequence,
            issue_date=dictamen.issue_date,
            pre_awarded_to=dictamen.pre_awarded_to,
            pre_award_total=dictamen.pre_award_total,
            currency=dictamen.currency,
            offers_count=dictamen.offers_count,
            legal_framework=dictamen.legal_framework,
            budget_imputation=dictamen.budget_imputation,
            source_url=source_url,
            scraped_at=datetime.utcnow(),
        ))

        known_signers = {s.username for s in self._dictamen_signers}
        already = {
            (e.dictamen_sequence, e.username) for e in self._evaluations
        }
        for ev in dictamen.evaluators:
            if ev.username not in known_signers:
                known_signers.add(ev.username)
                self._dictamen_signers.append(DictamenSignerModel(username=ev.username))
            if (sequence, ev.username) in already:
                continue
            already.add((sequence, ev.username))
            self._evaluations.append(EvaluatedByRelProps(
                process_number=self._process_number,
                dictamen_sequence=sequence,
                username=ev.username,
                role=ev.role,
                status=ev.status,
            ))

        for pa in dictamen.pre_adjudications:
            cuit = self._resolve_provider_cuit(pa.provider_name)
            if not cuit:
                logger.debug(
                    "Pre-adjudication provider not resolved for %s: %r",
                    self._process_number, pa.provider_name,
                )
                continue
            self._pre_adjudications.append(PreAdjudicatesRelProps(
                process_number=self._process_number,
                dictamen_sequence=sequence,
                provider_cuit=cuit,
                provider_name=pa.provider_name,
                group=pa.group,
                line_number=pa.line_number,
                alternative_number=pa.alternative_number,
                merit_order=pa.merit_order,
                is_primary=pa.is_primary,
                quantity=pa.quantity,
                unit_of_measure=pa.unit_of_measure,
                unit_price=pa.unit_price,
                total_per_line=pa.total_per_line,
                currency=pa.currency,
            ))

        for rj in dictamen.rejections:
            cuit = rj.provider_cuit or self._resolve_provider_cuit(rj.provider_name)
            if not cuit:
                logger.debug(
                    "Rejected provider not resolved for %s: %r",
                    self._process_number, rj.provider_name,
                )
                continue
            if rj.provider_name:
                self._add_providers([ProviderModel(cuit=cuit, business_name=rj.provider_name)])
            self._rejections.append(RejectedRelProps(
                process_number=self._process_number,
                dictamen_sequence=sequence,
                provider_cuit=cuit,
                provider_name=rj.provider_name,
                reasons=rj.reasons,
                justification=rj.justification,
            ))

    @staticmethod
    def _normalize_business_name(name: str | None) -> str | None:
        """Casefold and strip accents/punctuation/whitespace for name matching."""
        if not name:
            return None
        decomposed = unicodedata.normalize("NFKD", name.lower())
        without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
        compact = re.sub(r"[^a-z0-9]", "", without_accents)
        return compact or None

    def _resolve_provider_cuit(self, business_name: str | None) -> str | None:
        """Resolve a grid business name to a CUIT via the process's providers."""
        target = self._normalize_business_name(business_name)
        if not target:
            return None
        for provider in self._providers:
            if self._normalize_business_name(provider.business_name) == target:
                return provider.cuit
        return None

    def _apply_spr(self, spr: SPRPageResult) -> None:
        """Merge an SPR result into the accumulators."""
        if spr.provision_request:
            self._provision_requests.append(spr.provision_request)
        if spr.provider:
            self._add_providers([spr.provider])
        self._provision_request_lines.extend(spr.lines)

        self._merge_authorizers(spr.authorizers)
        self._authorizations_spr.extend(spr.authorizations)

    def _merge_authorizers(self, incoming: list[AuthorizerModel]) -> None:
        """Add authorizers by name, backfilling DNI from SPR pages onto OC-sourced records."""
        by_name = {a.full_name: a for a in self._authorizers}
        for a in incoming:
            existing = by_name.get(a.full_name)
            if existing is None:
                self._authorizers.append(a)
                by_name[a.full_name] = a
                continue
            if a.document_number and not existing.document_number:
                existing.document_number = a.document_number
                existing.document_type = a.document_type or existing.document_type

    def _build_result(self) -> ProcessResult:
        """Pack the accumulators into a ProcessResult, stamping the source."""
        page = self._page
        source = settings.source
        page.process.source = source
        if page.contracting_unit is not None:
            page.contracting_unit.source = source
        for req in page.procurement_requests:
            req.source = source
        for doc in self._contractual_documents:
            doc.source = source
        for line in self._contract_lines:
            line.source = source
        for dictamen in self._dictamenes:
            dictamen.source = source
        return ProcessResult(
            process=page.process,
            organization=page.organization,
            contracting_unit=page.contracting_unit,
            line_items=page.line_items,
            procurement_requests=page.procurement_requests,
            penalties=page.penalties,
            gde_documents=page.gde_documents,
            invites=page.invites,
            providers=self._providers,
            bids=self._bids,
            bid_lines=self._bid_lines,
            contractual_documents=self._contractual_documents,
            contract_lines=self._contract_lines,
            authorizers=self._authorizers,
            authorizations_cd=self._authorizations_cd,
            provision_requests=self._provision_requests,
            provision_request_lines=self._provision_request_lines,
            authorizations_spr=self._authorizations_spr,
            dictamenes=self._dictamenes,
            dictamen_signers=self._dictamen_signers,
            evaluations=self._evaluations,
            pre_adjudications=self._pre_adjudications,
            rejections=self._rejections,
        )


def _build_arg_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="coima-scraper",
        description="COMPR.AR scraper for the Coima anti-corruption project.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                                     # Use defaults from config.py / .env
  python main.py --batch-size 3                      # Custom Neo4j write batch size
  python main.py --tenders data/tenders.txt          # Custom input file
  python main.py --setup-schema-only                 # Create constraints/indexes then exit
  python main.py --force-schema                      # Re-apply schema even if already set up
  python main.py --reset-progress                    # Ignore saved progress, start fresh
  python main.py --rescrape-open                      # Re-scrape open processes from the last N months
  python main.py --rescrape-open --rescrape-months 6 # Re-scrape open processes from the last 6 months
  python main.py --refresh-indicators                # Update inflation/FX to latest then exit
        """,
    )
    parser.add_argument(
        "--source", "-s",
        choices=["comprar", "contratar"],
        default=None,
        help="Portal to scrape: 'comprar' (goods/services, default) or "
             "'contratar' (public works, contratar.gob.ar).",
    )
    parser.add_argument(
        "--tenders", "-t",
        default=None,
        help=f"Path to the tenders file (default: {settings.tenders_file}; "
             f"with --source contratar: {settings.contratar_tenders_file})",
    )
    parser.add_argument(
        "--batch-size", "-b",
        type=int,
        default=None,
        help=f"Number of processes per Neo4j write batch (default: {settings.batch_size})",
    )
    parser.add_argument(
        "--setup-schema-only",
        action="store_true",
        help="Apply Neo4j constraints/indexes and exit without scraping.",
    )
    parser.add_argument(
        "--force-schema",
        action="store_true",
        help="Re-apply Neo4j schema setup even if it was already applied to this database.",
    )
    parser.add_argument(
        "--reset-progress",
        action="store_true",
        help="Clear saved progress and re-scrape all processes from the beginning.",
    )
    parser.add_argument(
        "--rescrape-open",
        action="store_true",
        help="Re-scrape non-terminal (open) processes from the last N months "
             "(see --rescrape-months), reading them from Neo4j and bypassing "
             "the tenders file and saved progress.",
    )
    parser.add_argument(
        "--rescrape-months",
        type=int,
        default=None,
        help=f"Look-back window in months for --rescrape-open "
             f"(default: {settings.rescrape_months}).",
    )
    parser.add_argument(
        "--refresh-indicators",
        action="store_true",
        help="Re-fetch the latest inflation/FX indicators (advancing the "
             "inflation-adjustment reference date) then exit without scraping.",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=None,
        help=f"Log verbosity (default: {settings.log_level})",
    )
    return parser


def read_tenders(path: str) -> list[str]:
    """Read process numbers from a tenders file.

    One process number per line; `//` comments and empty lines are ignored.
    Uses utf-8-sig so a BOM at file start does not contaminate the first
    number.
    """
    tenders_path = pathlib.Path(path)
    if not tenders_path.exists():
        logger.error("Tenders file not found: %s", path)
        sys.exit(1)

    numbers: list[str] = []
    with tenders_path.open(encoding="utf-8-sig") as fh:
        for line in fh:
            clean = line.lstrip("﻿").split("//")[0].strip()
            if clean:
                numbers.append(clean)

    logger.info("Loaded %d process numbers from %s", len(numbers), path)
    return numbers


def setup_schema(force: bool = False) -> None:
    """Apply Neo4j constraints/indexes without scraping."""
    logger.info("Running schema setup only.")
    with Neo4jClient() as client:
        client.setup_schema(force=force)
    logger.info("Done.")


def refresh_indicators() -> None:
    """Re-fetch the latest inflation/FX observations without scraping."""
    logger.info("Refreshing economic indicators to the most recent data.")
    with Neo4jClient() as client:
        client.refresh_economic_indicators()
    logger.info("Done.")


def run_scrape(params: dict | None = None, on_progress=None, should_stop=None) -> dict:
    """Run the scrape pipeline and ingest pending processes into Neo4j.

    This is the programmatic core shared by the CLI (:func:`main`) and the
    container supervisor. The graceful-stop behaviour is identical to the CLI
    SIGINT handler: the current process finishes, the Neo4j batch is flushed,
    and progress is preserved for resume.

    Args:
        params: optional overrides - `reset_progress` (bool), `batch_size`
            (int), `log_level` (str), `force_schema` (bool), `tenders_file`
            (str), `rescrape_open` (bool), `rescrape_months` (int). When
            `rescrape_open` is set the work list is the non-terminal processes
            from the last `rescrape_months` months (read from Neo4j) instead of
            the tenders file, and the progress tracker is bypassed so already
            scraped processes are refreshed.
        on_progress: optional callback receiving a status dict (target,
            succeeded, failed, skipped, processes_scraped_count,
            current_process). Called at start, after each process, and on
            each batch flush so callers can persist live status.
        should_stop: optional callable returning True to request a graceful
            stop. Checked before each process.

    Returns:
        Summary dict: `{succeeded, failed, failed_list, skipped, target,
        stopped_early}`.
    """
    params = params or {}
    should_stop = should_stop or (lambda: False)

    # Apply overrides to settings.
    if params.get("source"):
        settings.apply_source(params["source"])
    if params.get("log_level"):
        settings.log_level = params["log_level"]
    if params.get("batch_size"):
        settings.batch_size = params["batch_size"]
    force_schema = bool(params.get("force_schema"))

    rescrape_open = bool(params.get("rescrape_open"))
    tenders_file = params.get("tenders_file") or settings.active_tenders_file

    logger.info("Coima scraper starting (source: %s, %s).", settings.source, settings.base_url)
    logger.info("Batch size  : %d", settings.batch_size)

    # Progress tracker (resume support), one file per source. Loaded in both
    # modes so the live scraped-count KPI is accurate; the open-process
    # re-scrape bypasses it for the work list and does not record into it.
    progress_path = pathlib.Path(settings.output_dir) / settings.progress_filename
    tracker = ProgressTracker(progress_path)

    if rescrape_open:
        months = int(params.get("rescrape_months") or settings.rescrape_months)
        logger.info("Mode: re-scrape open processes from the last %d months.", months)
        with Neo4jClient() as client:
            pending = client.get_open_process_numbers(months, settings.source)
        skipped = 0
        target = len(pending)
        logger.info("Re-scraping %d open (non-terminal) processes.", target)
    else:
        logger.info("Tenders file: %s", tenders_file)
        if not pathlib.Path(tenders_file).exists():
            raise FileNotFoundError(f"Tenders file not found: {tenders_file}")

        process_numbers = read_tenders(tenders_file)
        if params.get("reset_progress"):
            tracker.reset()

        pending = [pn for pn in process_numbers if not tracker.is_done(pn)]
        skipped = len(process_numbers) - len(pending)
        target = len(pending)

    failed: list[str] = []
    success_count = 0

    def _emit(current: str | None = None) -> None:
        if on_progress:
            on_progress({
                "target": target,
                "succeeded": success_count,
                "failed": len(failed),
                "skipped": skipped,
                "processes_scraped_count": tracker.completed_count,
                "current_process": current,
            })

    if skipped:
        logger.info("Skipping %d already-completed processes. %d remaining.", skipped, len(pending))

    if not pending:
        if rescrape_open:
            logger.info("No open (non-terminal) processes found in the look-back window.")
        else:
            logger.info("All processes already completed. Use reset_progress to re-run.")
        _emit()
        return {"succeeded": 0, "failed": 0, "failed_list": [],
                "skipped": skipped, "target": 0, "stopped_early": False}

    _emit()

    # Set up the Neo4j schema once per database (unless force_schema).
    neo4j_client = Neo4jClient()
    neo4j_client.setup_schema(force=force_schema)

    batch: list[ProcessResult] = []

    def _flush_neo4j_batch() -> None:
        """Commit the current batch to Neo4j and clear it."""
        if batch:
            logger.info("Flushing Neo4j batch (%d processes).", len(batch))
            try:
                neo4j_client.ingest_batch(batch)
            except Exception as exc:
                logger.error("Neo4j batch flush failed: %s", exc, exc_info=True)
            batch.clear()
            _emit()

    stopped_early = False
    try:
        with ScraperSession() as session:
            progress_bar = tqdm(pending, desc="Scraping", unit="process")
            for process_number in progress_bar:
                if should_stop():
                    stopped_early = True
                    logger.info("Stop requested. Exiting loop, progress saved.")
                    break

                progress_bar.set_postfix({"current": process_number})
                result = ScrapeOrchestrator(session, process_number).scrape()

                if result is None:
                    failed.append(process_number)
                    _emit(process_number)
                    continue

                batch.append(result)
                if len(batch) >= settings.batch_size:
                    _flush_neo4j_batch()

                if not rescrape_open:
                    tracker.mark_done(process_number)
                success_count += 1
                _emit(process_number)

        _flush_neo4j_batch()

    finally:
        neo4j_client.close()

    logger.info("=" * 60)
    logger.info(
        "Done: %d succeeded, %d failed, %d skipped (already done).",
        success_count, len(failed), skipped,
    )
    if failed:
        logger.warning("Failed: %s", ", ".join(failed))
    if stopped_early:
        logger.info("Scraper stopped early. Resume by running again (without reset_progress).")
    logger.info("=" * 60)
    _emit()

    return {"succeeded": success_count, "failed": len(failed), "failed_list": failed,
            "skipped": skipped, "target": target, "stopped_early": stopped_early}


def main() -> None:
    """CLI entry point: set up schema, then scrape and ingest pending processes."""
    parser = _build_arg_parser()
    args = parser.parse_args()

    if args.log_level:
        settings.log_level = args.log_level
    setup_logging(settings.log_level)

    if args.setup_schema_only:
        setup_schema(force=args.force_schema)
        return

    if args.refresh_indicators:
        refresh_indicators()
        return

    # Graceful shutdown flag for Ctrl+C / SIGINT.
    _stop_requested = False

    def _handle_sigint(signum, frame):
        nonlocal _stop_requested
        if not _stop_requested:
            _stop_requested = True
            logger.warning(
                "\n[bold yellow]Ctrl+C received. Finishing current process then stopping.[/bold yellow]\n"
                "Progress saved. Re-run without --reset-progress to resume."
            )
        else:
            logger.error("Forced exit.")
            sys.exit(1)

    signal.signal(signal.SIGINT, _handle_sigint)

    run_scrape(
        params={
            "source": args.source,
            "reset_progress": args.reset_progress,
            "batch_size": args.batch_size,
            "tenders_file": args.tenders,
            "force_schema": args.force_schema,
            "rescrape_open": args.rescrape_open,
            "rescrape_months": args.rescrape_months,
        },
        should_stop=lambda: _stop_requested,
    )


if __name__ == "__main__":
    main()

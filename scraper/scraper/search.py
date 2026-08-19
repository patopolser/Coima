"""
search.py - Process search on BuscarAvanzado.aspx.

Three-step ASP.NET navigation to reach VistaPreviaPliegoCiudadano:

  1. GET the search page to capture the initial VIEWSTATE.
  2. POST the process number to `btnListarPliegoNumero` to get a results
     table (each row is a `__doPostBack` link).
  3. POST a simulated click on the matched row; the server redirects to (or
     embeds the URL of) `VistaPreviaPliegoCiudadano.aspx?qs=<token>`.

Form field names discovered from live inspection:

  * Search input:         `ctl00$CPH1$txtNumeroProceso`
  * Number search button: `ctl00$CPH1$btnListarPliegoNumero`
  * Row link pattern:     `ctl00$CPH1$GridListaPliegos$ctlXX$lnkNumeroProceso`
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from config import settings
from scraper.session import ScraperSession
from utils.logging_config import get_logger
from utils.parsers import clean_text, make_absolute

logger = get_logger(__name__)


def _search_url() -> str:
    """Search page URL for the active source (base_url can change per run)."""
    return f"{settings.base_url}/BuscarAvanzado.aspx"

# Fixed hidden fields that must be included in every POST.
_FIXED_HIDDEN = {
    "ctl00_CPH1_devDteEdtFechaAperturaDesde_Raw": "N",
    "ctl00$CPH1$devDteEdtFechaAperturaDesde": "",
    "ctl00_CPH1_devDteEdtFechaAperturaDesde_DDDWS": "0:0:-1:0:0:0:0:0:",
    "ctl00_CPH1_devDteEdtFechaAperturaDesde_DDD_C_FNPWS": "0:0:-1:0:0:0:0:0:",
    "ctl00$CPH1$devDteEdtFechaAperturaDesde$DDD$C": "",
    "ctl00_CPH1_devDteEdtFechaAperturaHasta_Raw": "N",
    "ctl00$CPH1$devDteEdtFechaAperturaHasta": "",
    "ctl00_CPH1_devDteEdtFechaAperturaHasta_DDDWS": "0:0:-1:0:0:0:0:0:",
    "ctl00_CPH1_devDteEdtFechaAperturaHasta_DDD_C_FNPWS": "0:0:-1:0:0:0:0:0:",
    "ctl00$CPH1$devDteEdtFechaAperturaHasta$DDD$C": "",
    "ctl00$CPH1$hidEstadoListaPliegos": "NOREPORTEEXCEL",
    "ctl00_CPH1_devPopupListarProveedorWS": "0:0:-1:0:0:0:0:0:",
    "ctl00$CPH1$hdnFldIdProveedorSeleccionado": "",
    "ctl00_CPH1_devPopupVistaPreviaProcesoCompraCiudadanoWS": "0:0:-1:0:0:0:0:0:",
    "ctl00_CPH1_devPopupVistaPreviaPliegoWS": "0:0:-1:0:0:0:0:0:",
}


class ProcessFinder:
    """Locates a process's detail-page URL via the search form flow."""

    def __init__(self, session: ScraperSession) -> None:
        self._session = session

    def find(self, process_number: str) -> tuple[str | None, str | None]:
        """Search for a process and resolve its detail page URL and status.

        Args:
            process_number: e.g. "96-0043-LPR21", "14/3-0093-LPR24".

        Returns:
            A ``(detail_url, status)`` tuple; either element may be None when
            the process is not found or its URL cannot be resolved.
        """
        logger.info("Searching for process: %s", process_number)
        search_url = _search_url()

        # Step 0: contratar requires session cookies before the search page
        # resolves; no-op after the first call.
        self._session.warm_up()

        # Step 1: GET to capture VIEWSTATE and select defaults.
        html_get = self._session.get(search_url)
        viewstate_data = self._extract_form_state(html_get)

        # Step 2: POST the process number to get the results table.
        post_data_search = {
            **viewstate_data,
            "__EVENTTARGET": "ctl00$CPH1$btnListarPliegoNumero",
            "__EVENTARGUMENT": "",
            "__LASTFOCUS": "",
            "ctl00$CPH1$txtNumeroProceso": process_number,
            "ctl00$CPH1$txtExpediente": "",
            "ctl00$CPH1$txtNombrePliego": "",
            **_FIXED_HIDDEN,
        }
        html_results = self._session.post(search_url, data=post_data_search)

        # Step 3: find the matching row's postback target and status.
        row_target, process_status = self._find_row_postback_target(html_results, process_number)
        if not row_target:
            logger.warning("Process '%s' not found in search results.", process_number)
            return None, None

        logger.debug("Found row postback target: %s, status: %s", row_target, process_status)

        # Step 4: POST a simulated row click. VIEWSTATE changes after each POST,
        # so re-extract it from the results page.
        viewstate_data2 = self._extract_form_state(html_results)
        post_data_click = {
            **viewstate_data2,
            "__EVENTTARGET": row_target,
            "__EVENTARGUMENT": "",
            "__LASTFOCUS": "",
            "ctl00$CPH1$txtNumeroProceso": process_number,
            "ctl00$CPH1$txtExpediente": "",
            "ctl00$CPH1$txtNombrePliego": "",
            **_FIXED_HIDDEN,
        }
        detail_url = self._post_and_get_detail_url(post_data_click, process_number)

        if detail_url:
            logger.debug("Found detail URL for %s: %s", process_number, detail_url)
        else:
            logger.warning("Could not resolve detail URL for %s", process_number)

        return detail_url, process_status

    @staticmethod
    def _extract_form_state(html: str) -> dict[str, str]:
        """Extract ASP.NET VIEWSTATE fields and default <select> values."""
        soup = BeautifulSoup(html, "lxml")
        state: dict[str, str] = {}

        for field in ["__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION"]:
            el = soup.find("input", {"name": field})
            if el:
                state[field] = el.get("value", "")

        for sel in soup.find_all("select"):
            name = sel.get("name")
            if name:
                first_opt = sel.find("option")
                state[name] = first_opt.get("value", "") if first_opt else ""

        return state

    @staticmethod
    def _find_row_postback_target(
        html: str, process_number: str,
    ) -> tuple[str | None, str | None]:
        """Find the ``__doPostBack`` target and status for the matching row.

        Returns:
            A ``(target_id, status)`` tuple, e.g.
            ``("ctl00$CPH1$GridListaPliegos$ctl02$lnkNumeroProceso", "Adjudicado")``.
        """
        soup = BeautifulSoup(html, "lxml")
        dopostback_re = re.compile(r"__doPostBack\('([^']+)'", re.I)

        for a in soup.find_all("a"):
            text = clean_text(a.get_text()) or ""
            if text == process_number or process_number.strip().upper() in text.upper():
                href = a.get("href", "")
                m = dopostback_re.search(href)
                if m:
                    target = m.group(1)
                    parent_row = a.find_parent("tr")
                    status = None
                    if parent_row:
                        cells = parent_row.find_all("td")
                        idx = ProcessFinder._status_column_index(parent_row)
                        if idx is not None and idx < len(cells):
                            status = clean_text(cells[idx].get_text())
                        elif len(cells) > 5:
                            status = clean_text(cells[5].get_text())
                    return target, status

        return None, None

    @staticmethod
    def _status_column_index(row) -> int | None:
        """Locate the "Estado" column index from the results-table header.

        comprar puts the status in column 5 and contratar in column 4, so the
        index is resolved from the header text instead of being hardcoded.
        """
        table = row.find_parent("table")
        if table is None:
            return None
        header_row = table.find("tr")
        if header_row is None:
            return None
        for i, cell in enumerate(header_row.find_all(["th", "td"])):
            text = (clean_text(cell.get_text()) or "").lower()
            if text.startswith("estado"):
                return i
        return None

    def _post_and_get_detail_url(
        self, post_data: dict, process_number: str,
    ) -> str | None:
        """POST the row-click event and resolve the detail page URL.

        The server either redirects to the detail page, embeds its URL in the
        response HTML/script, or returns the detail page inline.
        """
        try:
            response = self._session._session.post(
                _search_url(),
                data=post_data,
                timeout=settings.request_timeout,
                allow_redirects=True,
            )
            response.raise_for_status()
        except Exception as exc:
            logger.error("Row click POST failed for %s: %s", process_number, exc)
            return None

        # Landed on the detail page directly after redirect.
        final_url = response.url
        if "VistaPreviaPliegoCiudadano" in final_url:
            return final_url

        soup = BeautifulSoup(response.text, "lxml")

        # Detail URL embedded in the response (popup or script). Keep any
        # leading section path (e.g. /PLIEGO/) so make_absolute resolves it.
        pliego_re = re.compile(r"(?:/[A-Za-z]+/)?VistaPreviaPliegoCiudadano\.aspx\?qs=[^'\"\s&]+", re.I)
        match = pliego_re.search(response.text)
        if match:
            return make_absolute(settings.base_url, match.group(0))

        # Meta refresh.
        meta = soup.find("meta", {"http-equiv": re.compile("refresh", re.I)})
        if meta and meta.get("content"):
            url_m = re.search(r"url=(.+)", meta["content"], re.I)
            if url_m:
                return make_absolute(settings.base_url, url_m.group(1).strip())

        # Any link to the detail page.
        for a in soup.find_all("a", href=re.compile(r"VistaPreviaPliegoCiudadano", re.I)):
            return make_absolute(settings.base_url, a["href"])

        # JS-set popup URL containing 'qs='.
        qs_re = re.compile(r"['\"]([^'\"]*VistaPreviaPliegoCiudadano[^'\"]*)['\"]", re.I)
        m2 = qs_re.search(response.text)
        if m2:
            return make_absolute(settings.base_url, m2.group(1))

        # Last resort: the response is the detail page itself (no redirect).
        if "Número de proceso" in response.text or "Objeto de la contratacion" in response.text:
            logger.debug("Response appears to be the detail page itself (no redirect).")
            return final_url

        logger.warning(
            "Could not find VistaPreviaPliegoCiudadano URL in row-click response for %s",
            process_number,
        )
        snippet_start = max(response.text.find("VistaPreviaPliego"), 0)
        logger.debug("Response snippet: %s", response.text[snippet_start:snippet_start + 500])
        return None

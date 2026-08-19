"""
export_dataset.py - Export the raw public procurement graph for open distribution.

Produces a redistributable snapshot of the scraped Neo4j graph (the *raw public
data*: processes, organizations, units, providers, bids, contracts, economic
indicators, etc.). It deliberately exports **only data that originates from public
sources** (comprar.gob.ar, INDEC, BCRA). It does NOT export any detection results,
risk scores, findings, or investigations -- those live in the backend SQLite store,
not in Neo4j, so they are never part of this dump.

Privacy: by default it REDACTS the identity-document fields of public officials
(`Authorizer.document_type` and `Authorizer.document_number`). Names of officials and
company CUITs are kept, as they are already public under procurement and
freedom-of-information law. Pass --include-document-numbers to keep them (not
recommended for public release; review with counsel first).

Output: one JSONL file per node label and one per relationship type, plus a
`manifest.json` with counts, the snapshot date, and the redaction policy. Reuses the
scraper's Neo4j connection settings (COIMA_NEO4J_* env vars / config.yaml).

Usage:
    python export_dataset.py                         # -> output/dataset/
    python export_dataset.py --out-dir my_export
    python export_dataset.py --include-document-numbers   # keep DNI fields (careful)
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import pathlib

from neo4j import GraphDatabase

from config import settings

# Neo4j internal/bookkeeping labels that must never be exported.
_INTERNAL_LABELS = {"_SchemaMeta"}

# Properties stripped from exported nodes unless explicitly kept. Keyed by label.
_REDACTED_PROPERTIES = {
    "Authorizer": {"document_type", "document_number"},
}


def _node_labels(driver) -> list[str]:
    with driver.session() as s:
        rows = s.run("CALL db.labels() YIELD label RETURN label ORDER BY label").data()
    return [r["label"] for r in rows if r["label"] not in _INTERNAL_LABELS]


def _relationship_types(driver) -> list[str]:
    with driver.session() as s:
        rows = s.run(
            "CALL db.relationshipTypes() YIELD relationshipType "
            "RETURN relationshipType AS t ORDER BY t"
        ).data()
    return [r["t"] for r in rows]


def _redact(label: str, props: dict, keep_documents: bool) -> dict:
    if keep_documents:
        return props
    drop = _REDACTED_PROPERTIES.get(label)
    if not drop:
        return props
    return {k: v for k, v in props.items() if k not in drop}


def _export_nodes(driver, label: str, out_dir: pathlib.Path, keep_documents: bool) -> int:
    path = out_dir / f"nodes_{label}.jsonl"
    count = 0
    with driver.session() as s, path.open("w", encoding="utf-8") as fh:
        # elementId gives a stable per-snapshot id used to join relationships.
        result = s.run(
            f"MATCH (n:`{label}`) RETURN elementId(n) AS id, properties(n) AS props"
        )
        for rec in result:
            row = {
                "id": rec["id"],
                "label": label,
                "properties": _redact(label, rec["props"], keep_documents),
            }
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            count += 1
    if count == 0:
        path.unlink(missing_ok=True)
    return count


def _export_relationships(driver, rel_type: str, out_dir: pathlib.Path) -> int:
    path = out_dir / f"rels_{rel_type}.jsonl"
    count = 0
    with driver.session() as s, path.open("w", encoding="utf-8") as fh:
        result = s.run(
            f"MATCH (a)-[r:`{rel_type}`]->(b) "
            "RETURN elementId(a) AS start, elementId(b) AS end, "
            "type(r) AS type, properties(r) AS props"
        )
        for rec in result:
            row = {
                "start": rec["start"],
                "end": rec["end"],
                "type": rec["type"],
                "properties": rec["props"],
            }
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            count += 1
    if count == 0:
        path.unlink(missing_ok=True)
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the raw public graph for distribution.")
    parser.add_argument(
        "--out-dir",
        default=str(pathlib.Path(settings.output_dir) / "dataset"),
        help="Output directory (default: <output_dir>/dataset).",
    )
    parser.add_argument(
        "--include-document-numbers",
        action="store_true",
        help="Keep Authorizer document_type/document_number (NOT recommended for public release).",
    )
    args = parser.parse_args()

    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    keep_documents = args.include_document_numbers

    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )

    node_counts: dict[str, int] = {}
    rel_counts: dict[str, int] = {}
    try:
        for label in _node_labels(driver):
            node_counts[label] = _export_nodes(driver, label, out_dir, keep_documents)
            print(f"  nodes  {label}: {node_counts[label]}")
        for rel_type in _relationship_types(driver):
            rel_counts[rel_type] = _export_relationships(driver, rel_type, out_dir)
            print(f"  rels   {rel_type}: {rel_counts[rel_type]}")
    finally:
        driver.close()

    manifest = {
        "snapshot_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "source": "comprar.gob.ar + contratar.gob.ar (public procurement) + INDEC (CPI) + BCRA (FX)",
        "contains_detection_results": False,
        "document_numbers_redacted": not keep_documents,
        "redacted_properties": {} if keep_documents else _REDACTED_PROPERTIES,
        "node_counts": node_counts,
        "relationship_counts": rel_counts,
        "format": "JSON Lines; nodes_<Label>.jsonl and rels_<Type>.jsonl; "
        "node ids join to relationship start/end.",
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    total_nodes = sum(node_counts.values())
    total_rels = sum(rel_counts.values())
    print(f"\nExported {total_nodes} nodes and {total_rels} relationships to {out_dir}")
    if not keep_documents:
        print("Authorizer document_type/document_number were REDACTED.")


if __name__ == "__main__":
    main()

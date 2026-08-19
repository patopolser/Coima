# Coima Dataset — Argentine Public Procurement Graph

This is a redistributable snapshot of **public** Argentine government procurement data
scraped from [comprar.gob.ar](https://comprar.gob.ar) (goods and services) and
[contratar.gob.ar](https://contratar.gob.ar) (public works), enriched with public economic
indicators (INDEC CPI, BCRA FX). It is produced by
[`scraper/export_dataset.py`](scraper/export_dataset.py).

> **Read first:** This dataset contains **only raw public data**. It does **not** contain
> any detection results, risk scores, flags, or accusations. The presence of an entity in
> this dataset says nothing about its conduct. See [DISCLAIMER.md](DISCLAIMER.md).

## Provenance

| Field | Value |
|---|---|
| Primary sources | comprar.gob.ar and contratar.gob.ar (public "Ciudadano" pages) |
| Inflation (CPI) | INDEC IPC Nivel General Nacional |
| Exchange rates | BCRA Estadisticas Cambiarias |
| Snapshot date | see `manifest.json` |
| Detection results included | No |
| Document numbers (DNI) | Redacted by default |

## Privacy / personal data

The dataset may include **names and roles of public officials** and **company
identifiers (CUIT)**, which are already public under Argentina's procurement and
freedom-of-information framework, processed here for transparency and civic oversight.

Identity-document fields of officials (`Authorizer.document_type`,
`Authorizer.document_number`) are **redacted** by the export script unless explicitly
overridden. If you are listed and believe a record is inaccurate or harmful, see the
right-of-reply / takedown procedure in [DISCLAIMER.md](DISCLAIMER.md) §5.

## Format

- `nodes_<Label>.jsonl` — one JSON object per line: `{id, label, properties}`.
- `rels_<Type>.jsonl` — one JSON object per line: `{start, end, type, properties}`.
  `start`/`end` reference node `id`s within the same snapshot.
- `manifest.json` — snapshot date, sources, redaction policy, and per-label/-type counts.

The graph schema (node labels and relationships) is documented in
[scraper/SCHEMA.md](scraper/SCHEMA.md).

## License

This dataset is distributed under **Creative Commons Attribution 4.0 International
(CC BY 4.0)**. Attribute "Coima" and the original sources (comprar.gob.ar,
contratar.gob.ar). The data is
provided "AS IS", without warranty; accuracy depends on the original public source.

## Regenerating

```bash
cd scraper
python export_dataset.py            # writes output/dataset/
```

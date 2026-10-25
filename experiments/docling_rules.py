"""Option B, no LLM: Docling (layout + table structure + OCR) -> deterministic column mapping.

Runs in a separate venv (pip install docling). Same extract(path) contract as extract.py,
so eval/run.py can score it:  <docling-venv>/python eval/run.py experiments/docling_rules.py runs/docling/rules_r1
"""
import re
import sys
from pathlib import Path

from docling.document_converter import DocumentConverter

MODEL = "docling-rules (no LLM)"
_converter = None

COLUMNS = {   # header keyword -> schema field; first match wins, checked in this order
    "test_name": ("test", "investigation", "parameter", "name"),
    "reference_range": ("range", "interval", "reference", "normal"),
    "unit": ("unit",),
    "value": ("result", "value", "observed"),
}
UNIT = r"(%|/hpf|/cumm|[a-zA-Zµμ]+/[a-zA-Z0-9]+|mill/cumm|lakh/cumm|mm/hr|U/L|fL|pg)"


def converter() -> DocumentConverter:
    global _converter
    if _converter is None:        # model load is the cold-start cost; reuse across reports
        _converter = DocumentConverter()
    return _converter


def map_columns(headers: list[str]) -> dict[str, int]:
    found = {}
    for field, keywords in COLUMNS.items():
        for i, h in enumerate(headers):
            if i not in found.values() and any(k in h.lower() for k in keywords):
                found[field] = i
                break
    return found


def split_unit(text: str) -> tuple[str, str | None]:
    """'179 ng/dL' -> ('179', 'ng/dL'); '0 - 5 /hpf' -> ('0 - 5', '/hpf')."""
    m = re.match(rf"^(.*?\S)\s*{UNIT}$", text.strip())
    return (m.group(1).strip(), m.group(2)) if m else (text.strip(), None)


def rows_from_table(df) -> list[dict]:
    headers = [str(c) for c in df.columns]
    cols = map_columns(headers)
    if "test_name" not in cols or "value" not in cols:
        return []
    out = []
    for _, r in df.iterrows():
        cell = lambda f: str(r.iloc[cols[f]]).strip() if f in cols and str(r.iloc[cols[f]]).strip() not in ("", "nan") else None
        name, value = cell("test_name"), cell("value")
        if not name or not value or name.lower() == headers[cols["test_name"]].lower():   # repeated header row
            continue
        unit, rng = cell("unit"), cell("reference_range")
        if unit is None:
            value, unit = split_unit(value)
        if rng is not None:
            rng, range_unit = split_unit(rng)
            unit = unit or range_unit
        out.append({"test_name": name, "value": value, "unit": unit, "reference_range": rng})
    return out


def extract(path: Path) -> dict:
    doc = converter().convert(str(path)).document
    tests = []
    for table in doc.tables:
        tests += rows_from_table(table.export_to_dataframe(doc=doc))
    return {"tests": tests}


if __name__ == "__main__":
    import json
    print(json.dumps(extract(Path(sys.argv[1])), indent=2, ensure_ascii=False))

"""Option C: Docling markdown -> Gemini as TEXT (no image), with the final prompt and schema.
Isolates whether Docling's perception (OCR + table structure) beats the model reading the page itself.
Docling output is cached in runs/docling/cache so the slow conversion is done once per report."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import extract as final  # noqa: E402

MODEL = final.MODEL
CACHE = ROOT / "runs" / "docling" / "cache"


def docling_markdown(path: Path) -> str:
    cached = CACHE / f"{path.stem}.md"
    if not cached.exists():
        from docling.document_converter import DocumentConverter
        CACHE.mkdir(parents=True, exist_ok=True)
        cached.write_text(DocumentConverter().convert(str(path)).document.export_to_markdown(), encoding="utf-8")
    return cached.read_text(encoding="utf-8")


def extract(path: Path) -> dict:
    part = {"text": "Lab report, converted to markdown by a document parser:\n\n" + docling_markdown(path)}
    return {"tests": final.clean(final.parse(final.call_model([part])))}

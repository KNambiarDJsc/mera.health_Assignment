"""Final extractor with one change: PDFs rendered at 60 DPI (the baseline's value) instead of 200.
Tests whether resolution still matters once prompt/schema are fixed."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import extract as final  # noqa: E402

final.DPI = 60
MODEL = final.MODEL
extract = final.extract

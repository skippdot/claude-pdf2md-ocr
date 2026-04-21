"""OCR plugin for claude-pdf2md."""

from .enricher import OcrEnricher
from .pipeline import convert_with_ocr

__all__ = ["OcrEnricher", "convert_with_ocr"]
__version__ = "0.0.2"

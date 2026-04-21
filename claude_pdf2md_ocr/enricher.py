"""Per-page `PageEnricher` implementation for Tesseract-based OCR.

Plugged into `claude_pdf2md.convert_to_string(enrichers=[...])`. The base
package calls `enrich(mu_page, page)` once per page after its own
text-layer extraction and before tables / images / structure / emit. We
use that window to fill `page.blocks` with recognised-text blocks on
scanned pages, and to drop redundant full-page background images that
would otherwise duplicate the content we just recognised."""

from __future__ import annotations

import fitz
from claude_pdf2md.model import ImageAnnot, Page

from .backends import OcrBackend, OcrWord
from .inject import words_to_blocks
from .spellcheck import fix_word, languages_for

_WHOLE_PAGE_IMAGE_RATIO = 0.8
_MIN_BODY_CHARS = 200


class OcrEnricher:
    def __init__(
        self,
        backend: OcrBackend,
        lang: str,
        dpi: int,
        min_confidence: float,
        only_empty_pages: bool,
        spellcheck: bool,
    ) -> None:
        self._backend = backend
        self._lang = lang
        self._dpi = dpi
        self._min_confidence = min_confidence
        self._only_empty_pages = only_empty_pages
        self._spellcheck = spellcheck

    def enrich(self, mu_page: fitz.Page, page: Page) -> None:
        if self._only_empty_pages and _has_text(page):
            return
        png_bytes = mu_page.get_pixmap(dpi=self._dpi).tobytes("png")
        words = self._backend.recognise(
            image_bytes=png_bytes,
            pdf_width_pt=page.width,
            pdf_height_pt=page.height,
            dpi=self._dpi,
            lang=self._lang,
        )
        if not words:
            return
        if self._spellcheck:
            words = _apply_spellcheck(words)
        page.blocks = words_to_blocks(words, min_confidence=self._min_confidence)
        # Preserve inline images (logos, stamps, QR codes) but drop whole-page
        # rasters — on an OCR'd page those are just a picture of the same
        # text we just recognised, so keeping both doubles the output size.
        # Filter `page.images` directly so `images.write_assets` never saves
        # the redundant PNG to disk.
        page.images = [img for img in page.images if not _is_whole_page_image(img, page)]


def _apply_spellcheck(words: list[OcrWord]) -> list[OcrWord]:
    page_text = " ".join(w.text for w in words)
    langs = languages_for(page_text)
    return [
        OcrWord(
            text=fix_word(w.text, langs),
            x0=w.x0,
            y0=w.y0,
            x1=w.x1,
            y1=w.y1,
            confidence=w.confidence,
            line_id=w.line_id,
        )
        for w in words
    ]


def _is_whole_page_image(img: ImageAnnot, page: Page) -> bool:
    if page.width <= 0 or page.height <= 0:
        return False
    img_area = (img.bbox.x1 - img.bbox.x0) * (img.bbox.y1 - img.bbox.y0)
    page_area = page.width * page.height
    return img_area / page_area > _WHOLE_PAGE_IMAGE_RATIO


def _has_text(page: Page) -> bool:
    """Pre-filter for scan-style pages that should be OCR'd.

    Hybrid scans are common in legal PDFs: the page is a rasterised scan
    with just a handful of overlay URLs or signature strings on top. If
    the page also carries a whole-page image, we demand ≥ 200 chars of
    real body text before trusting the text layer — otherwise OCR is
    what actually recovers the content.
    """
    text_chars = sum(len(line.text.strip()) for block in page.blocks if block.kind != "image" for line in block.lines)
    has_whole_page_image = any(_is_whole_page_image(img, page) for img in page.images)
    min_chars = _MIN_BODY_CHARS if has_whole_page_image else 1
    return text_chars >= min_chars

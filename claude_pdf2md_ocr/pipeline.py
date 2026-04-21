"""End-to-end OCR + markdown conversion pipeline.

Since `claude-pdf2md` ≥ 0.1.2 exposes an `enrichers=` hook on
`convert_to_string`, this module is a thin wrapper that:

1. Opens the PDF once with PyMuPDF to sniff / probe the document's language
   (that's cross-page work the per-page enricher can't do on its own),
   closing the handle immediately afterwards.
2. Hands off to the base package's `convert(…, enrichers=[OcrEnricher(…)])`,
   letting it own extract → tables → images → structure → emit exactly as
   it would for a native PDF. The enricher itself is called once per page
   between extract and the rest.
"""

from __future__ import annotations

from pathlib import Path

import fitz
from claude_pdf2md import convert

from .backends import OcrBackend
from .backends.tesseract import TesseractBackend
from .enricher import OcrEnricher
from .spellcheck import detect_tesseract_lang

_AUTO_LANG = "auto"
# When we can't tell what language a fully-scanned document is in, hand
# Tesseract every pack we ship support for. The enricher's downstream
# spellcheck pass then cleans up the cross-script confusion that comes
# with a multi-language model.
_FALLBACK_TESSERACT_LANG = "ukr+rus+eng+ces"

_DEFAULT_DPI = 200  # Tesseract's sweet spot for small body text on A4 scans.
_PROBE_DPI = 120  # Lower DPI for the language-detection probe pass — faster, enough signal.
_MIN_BODY_CHARS = 200
_WHOLE_PAGE_IMAGE_RATIO = 0.8


def convert_with_ocr(
    pdf_path: str | Path,
    output: str | Path | None = None,
    assets_dir: str | Path | None = None,
    include_title: bool = False,
    lang: str = _AUTO_LANG,
    only_empty_pages: bool = True,
    min_confidence: float = 0.5,
    backend: OcrBackend | None = None,
    dpi: int = _DEFAULT_DPI,
    spellcheck: bool = True,
) -> str:
    backend = backend or TesseractBackend()
    pdf_path = str(pdf_path)

    resolved_lang = _resolve_lang(pdf_path, lang, backend, only_empty_pages)

    enricher = OcrEnricher(
        backend=backend,
        lang=resolved_lang,
        dpi=dpi,
        min_confidence=min_confidence,
        only_empty_pages=only_empty_pages,
        spellcheck=spellcheck,
    )
    return convert(
        pdf_path,
        output=output,
        assets_dir=assets_dir,
        include_title=include_title,
        enrichers=[enricher],
    )


def _resolve_lang(pdf_path: str, lang: str, backend: OcrBackend, only_empty_pages: bool) -> str:
    """Pick a Tesseract `--lang` string for this document.

    Three-stage decision for ``lang == "auto"``:

    1. Sample the existing text layer across pages; if it's substantive,
       `detect_tesseract_lang` picks a narrow pair like `ces+eng`.
    2. Otherwise run a cheap probe OCR pass (120 DPI, fallback lang) on the
       first page that would be OCR'd. Detection on the probe output
       often yields a narrow pack anyway, avoiding multi-language confusion
       on the real pass.
    3. If both steps produce too little text, return the broad fallback mix
       and let the enricher's spellcheck pass clean up script confusion.
    """
    if lang != _AUTO_LANG:
        return lang

    mu = fitz.open(pdf_path)
    try:
        text_sample = _text_layer_sample(mu)
        detected = detect_tesseract_lang(text_sample)
        if detected:
            return detected
        probe_text = _probe_ocr_sample(mu, backend, only_empty_pages)
        if probe_text:
            detected = detect_tesseract_lang(probe_text)
            if detected:
                return detected
    finally:
        mu.close()
    return _FALLBACK_TESSERACT_LANG


def _text_layer_sample(mu: fitz.Document, limit: int = 4000) -> str:
    """Concatenate the text-layer content across pages, up to `limit` chars."""
    parts: list[str] = []
    size = 0
    for pno in range(mu.page_count):
        text = mu.load_page(pno).get_text().strip()
        if not text:
            continue
        parts.append(text)
        size += len(text) + 1
        if size >= limit:
            break
    return "\n".join(parts)


def _probe_ocr_sample(mu: fitz.Document, backend: OcrBackend, only_empty_pages: bool) -> str:
    """Run a cheap OCR pass on the first would-be-OCR page for lang sniffing."""
    probe_pno = _first_ocr_candidate(mu, only_empty_pages)
    if probe_pno is None:
        return ""
    mu_page = mu.load_page(probe_pno)
    png_bytes = mu_page.get_pixmap(dpi=_PROBE_DPI).tobytes("png")
    words = backend.recognise(
        image_bytes=png_bytes,
        pdf_width_pt=mu_page.rect.width,
        pdf_height_pt=mu_page.rect.height,
        dpi=_PROBE_DPI,
        lang=_FALLBACK_TESSERACT_LANG,
    )
    return " ".join(w.text for w in words)


def _first_ocr_candidate(mu: fitz.Document, only_empty_pages: bool) -> int | None:
    """Pick the first page index that `OcrEnricher` would process, for probing."""
    if not only_empty_pages:
        return 0 if mu.page_count > 0 else None
    for pno in range(mu.page_count):
        mu_page = mu.load_page(pno)
        if not _mu_page_has_text(mu_page):
            return pno
    return None


def _mu_page_has_text(mu_page: fitz.Page) -> bool:
    """Mirror of the enricher's `_has_text` check, using only a PyMuPDF page.

    Kept in sync with `OcrEnricher._has_text` so the language-probe path
    picks the same set of pages the enricher will later OCR."""
    text = mu_page.get_text().strip()
    has_whole_page_image = any(
        _whole_page_image_ratio(mu_page, xref) > _WHOLE_PAGE_IMAGE_RATIO
        for (xref, *_rest) in mu_page.get_images(full=True)
    )
    min_chars = _MIN_BODY_CHARS if has_whole_page_image else 1
    return len(text) >= min_chars


def _whole_page_image_ratio(mu_page: fitz.Page, xref: int) -> float:
    page_area = mu_page.rect.width * mu_page.rect.height
    if page_area <= 0:
        return 0.0
    best = 0.0
    for rect in mu_page.get_image_rects(xref):
        ratio = (rect.width * rect.height) / page_area
        best = max(best, ratio)
    return best

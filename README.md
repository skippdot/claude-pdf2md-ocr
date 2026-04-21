# claude-pdf2md-ocr

OCR plugin for [`claude-pdf2md`](https://github.com/skippdot/claude-pdf2md).
Detects PDF pages that have no usable text layer (pure scans, hybrid scans
with minimal overlay) and fills them in using Tesseract, so that the
existing `claude-pdf2md` pipeline — headings, lists, tables, links — works
on scanned documents the same way it works on native PDFs.

## Features

- **Auto language detection.** Sniffs the document's text layer (or a cheap
  first-pass OCR probe when the text layer is missing) and picks a narrow
  Tesseract pack like `ces+eng` or `ukr+eng`. Avoids the cross-script
  confusion that plagues a default `ukr+rus+eng` model on Czech or English
  documents.
- **Post-OCR spellcheck.** Cleans up the cross-script errors that do slip
  through (`опе → one`, `Ме → №`, `Мо1224 → №1224`, `ІВАМ → IBAN`, `І → I`)
  by running each token against a language-aware `wordfreq` dictionary.
  Conservative — only edits a token when the correction is unambiguous.
- **Smart page selection.** By default OCR runs only on pages that are
  scans (no text layer, or a whole-page background image + tiny text
  overlay). `--all-pages` forces it on every page.
- **Heading-safe injection.** OCR word heights are normalised to a per-page
  median so the base pipeline's heading detector stops treating every line
  with tall capitals as a tier-2 heading.

## System dependency

Tesseract must be installed separately.

```bash
# macOS
brew install tesseract tesseract-lang     # ships 100+ language packs

# Debian / Ubuntu
sudo apt-get install tesseract-ocr tesseract-ocr-ukr tesseract-ocr-rus \
                     tesseract-ocr-ces tesseract-ocr-eng

# verify
tesseract --list-langs | grep -E '^(ukr|rus|ces|eng)$'
```

## Install

```bash
pip install claude-pdf2md-ocr                             # once on PyPI
# or, while the package is still a prototype:
pip install git+https://github.com/skippdot/claude-pdf2md-ocr
```

## Usage

```bash
# Auto language detection (default). Tesseract gets a narrow pack based on
# the PDF's text layer or a cheap probe pass.
claude-pdf2md-ocr scan.pdf -o out.md

# Force an explicit Tesseract language string when you know the document:
claude-pdf2md-ocr scan.pdf -o out.md --lang ces+eng

# OCR every page, even those that already have a text layer:
claude-pdf2md-ocr scan.pdf -o out.md --all-pages

# Skip the post-OCR spellcheck pass:
claude-pdf2md-ocr scan.pdf -o out.md --no-spellcheck
```

Or programmatically:

```python
from claude_pdf2md_ocr import convert_with_ocr

md = convert_with_ocr("scan.pdf")                 # auto-detect lang
md = convert_with_ocr("scan.pdf", lang="ces+eng") # explicit override
```

## Status

Prototype. Published to PyPI once accuracy on real scanned Ukrainian /
Czech legal documents stabilises and the base `claude-pdf2md` package
grows the `enrichers=` hook that will collapse this package's bespoke
pipeline composition into a one-liner.

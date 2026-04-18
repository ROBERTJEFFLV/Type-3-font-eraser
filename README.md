# Type-3 Font Eraser

`pdf_text_replace.py` is a small utility for covering existing PDF text and writing replacement text back with a configurable font. It is useful when you want to avoid Type 3 font fallback and keep replacement output controllable from a YAML config.

## Features

- Extracts text spans from a PDF with PyMuPDF
- Merges nearby spans into logical text boxes
- Samples surrounding background colors to cover original text
- Rewrites text with a configurable font, size, and color
- Supports built-in PyMuPDF fonts and external TTF/OTF font files

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
python pdf_text_replace.py --input input.pdf --output output.pdf --config config.yaml
```

## Files

```text
pdf_replace_project/
├─ pdf_text_replace.py
├─ config.yaml
├─ requirements.txt
├─ .gitignore
└─ README.md
```

## Notes

- `output.pdf` is a generated file and is not tracked.
- `input_pdf/` and `tmp_test/` are local sample/test artifact directories and are not tracked.

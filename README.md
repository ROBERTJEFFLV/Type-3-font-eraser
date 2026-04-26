# Type-3 Font Eraser

`pdf_text_replace.py` is a small utility for covering existing PDF text and writing replacement text back with a configurable font. It is useful when you want to avoid Type 3 font fallback and keep replacement output controllable from a YAML config.

The repository also includes `pdf_text_replace_ui.py`, a local Tkinter interface for previewing and tuning the workflow with a side-by-side PDF comparison.

## Features

- Extracts text spans from a PDF with PyMuPDF
- Merges nearby spans into logical text boxes
- Samples surrounding background colors to cover original text
- Rewrites text with a configurable font, size, and color
- Supports built-in PyMuPDF fonts and external TTF/OTF font files
- Provides a two-page comparison UI: original PDF on the left, processed PDF on the right
- Separates user controls into two workflow stages: erase/cover tuning and replacement-text tuning
- Runs a quick output diagnosis to report whether Type 3 fonts are still detected

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Tkinter is used for the UI. On Ubuntu/Debian, install it if your Python build does not include it:

```bash
sudo apt install python3-tk
```

## Command-line usage

```bash
python pdf_text_replace.py --input input.pdf --output output.pdf --config config.yaml
```

## UI usage

```bash
python pdf_text_replace_ui.py
```

Recommended UI workflow:

1. Choose the input PDF.
2. Choose an output PDF path.
3. Adjust the `1 Erase` tab first. This controls background sampling, foreground detection, padding, and frame-line protection.
4. Adjust the `2 Text` tab. This controls replacement font, font size, and text color.
5. Click `Run processing`.
6. Compare the original and processed pages side by side. Use the page and zoom controls to inspect suspicious regions.
7. If needed, tune the parameters and run again.

## Why the UI separates erase and text controls

The tool is fundamentally doing two different operations:

1. Erase / cover: detect the original glyph pixels, sample a nearby background color, and cover the old text without damaging surrounding graphics.
2. Text replacement: write replacement text back using a controlled font, size, and color.

These two steps fail in different ways, so their controls are separated in the UI.

Common erase-stage problems:

- The cover box is too large and damages table borders, figure frames, or diagram lines.
- The cover box is too small and leaves old glyph edges visible.
- The sampled background color does not match the real local background.
- The PDF contains dense vector graphics, gradients, transparency, or rasterized text.

Common text-stage problems:

- The selected font does not support the required glyphs.
- The replacement text overflows the original box.
- The font size visually differs from the source text.
- Type 3 fonts remain because other PDF objects still use Type 3 fonts or because the selected font path is unsuitable.

The UI includes controls for the parameters users most often need to personalize: font file, font size, text color, DPI, background sampling, glyph-detection tolerance, padding, character margin, and line-safety behavior.

## Files

```text
pdf_replace_project/
├─ pdf_text_replace.py
├─ pdf_text_replace_ui.py
├─ config.yaml
├─ requirements.txt
├─ .gitignore
└─ README.md
```

## Notes

- `output.pdf` is a generated file and is not tracked.
- `input_pdf/` and `tmp_test/` are local sample/test artifact directories and are not tracked.
- Always inspect the rendered output visually. PDF text replacement is not fully reliable for complex vector drawings, scanned PDFs, transparent layers, or mathematical notation.

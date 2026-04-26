#!/usr/bin/env python3
"""
Streamlit UI for Type-3 Font Eraser.

Run:
    streamlit run ui_app.py

The UI keeps the existing pdf_text_replace.py script as the processing engine.
It focuses on three tasks:
    1. Build a YAML config from user-friendly controls.
    2. Run the PDF text erase/rewrite workflow.
    3. Preview the original and processed PDF side by side for manual review.
"""
from __future__ import annotations

import io
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import fitz  # PyMuPDF
from PIL import Image, ImageChops, ImageDraw, ImageEnhance
import streamlit as st
import yaml

ROOT = Path(__file__).resolve().parent
ENGINE = ROOT / "pdf_text_replace.py"
DEFAULT_CONFIG = ROOT / "config.yaml"


BASE_CONFIG: Dict[str, Any] = {
    "font_family": "auto",
    "font_size": None,
    "fill_color": "#333333",
    "dpi": 300,
    "merge_threshold_pt": 1.5,
    "background_sample_ring": 3,
    "background_histogram_step": 8,
    "foreground_tolerance": 24,
    "tight_box_padding_px": 0,
    "char_box_margin_px": 1,
    "thin_component_thickness_px": 1,
    "thin_component_span_ratio": 0.1,
    "min_foreground_component_px": 4,
    "line_boundary_search_px": 40,
    "line_boundary_margin_px": 0,
    "char_probe_shrink_ratio": 0.25,
    "page_line_axis_tolerance_pt": 0.25,
    "page_line_merge_tolerance_pt": 1.0,
    "page_line_min_span_pt": 8,
    "page_line_safety_px": 1,
}

PRESETS: Dict[str, Dict[str, Any]] = {
    "Balanced: normal paper correction": {},
    "Conservative: protect figures and table lines": {
        "tight_box_padding_px": 0,
        "char_box_margin_px": 0,
        "foreground_tolerance": 30,
        "thin_component_thickness_px": 1,
        "thin_component_span_ratio": 0.1,
        "line_boundary_search_px": 50,
        "page_line_safety_px": 2,
    },
    "Aggressive: remove visible text remnants": {
        "tight_box_padding_px": 2,
        "char_box_margin_px": 2,
        "foreground_tolerance": 18,
        "background_sample_ring": 5,
        "thin_component_thickness_px": 2,
        "line_boundary_search_px": 30,
        "page_line_safety_px": 1,
    },
    "Low resolution preview/test run": {
        "dpi": 180,
        "background_sample_ring": 3,
        "foreground_tolerance": 24,
    },
}


MANUAL_REVIEW_ITEMS = [
    {
        "Area": "Erasing",
        "Likely problem": "The cover rectangle is too large and touches a frame, axis, table line, or diagram border.",
        "Useful control": "Use the Conservative preset; reduce tight_box_padding_px and char_box_margin_px; increase page_line_safety_px.",
    },
    {
        "Area": "Erasing",
        "Likely problem": "Old text is still faintly visible after processing.",
        "Useful control": "Use the Aggressive preset; increase tight_box_padding_px; reduce foreground_tolerance slightly.",
    },
    {
        "Area": "Erasing",
        "Likely problem": "Background is not pure white, so the covered area looks like a patch.",
        "Useful control": "Increase background_sample_ring or background_histogram_step; inspect the side-by-side preview.",
    },
    {
        "Area": "Text adding",
        "Likely problem": "New text does not match the original font or is shifted.",
        "Useful control": "Use font_family=auto/original first; otherwise upload a known TTF/OTF font and adjust font_size.",
    },
    {
        "Area": "Text adding",
        "Likely problem": "Chinese or special characters are missing.",
        "Useful control": "Use a font file that contains those glyphs; avoid relying only on built-in PDF fonts.",
    },
    {
        "Area": "Final PDF check",
        "Likely problem": "A page contains complex rotated text, formula glyphs, or already-rasterized text.",
        "Useful control": "Review that page manually; the automatic span-based workflow may not fully fix it.",
    },
]


def load_yaml_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return dict(BASE_CONFIG)
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    config = dict(BASE_CONFIG)
    config.update(data)
    return config


def dump_yaml(config: Dict[str, Any]) -> str:
    return yaml.safe_dump(config, allow_unicode=True, sort_keys=False)


def safe_filename(name: str, fallback: str = "input.pdf") -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in name)
    return cleaned or fallback


def render_page(pdf_bytes: bytes, page_index: int, dpi: int, draw_boxes: bool, config: Dict[str, Any]) -> Image.Image:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page_index = max(0, min(page_index, len(doc) - 1))
    page = doc[page_index]
    zoom = dpi / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    image = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")

    if draw_boxes:
        draw = ImageDraw.Draw(image)
        for box in extract_text_boxes(page, config):
            x0, y0, x1, y1 = [int(round(v * zoom)) for v in box]
            draw.rectangle((x0, y0, x1, y1), outline=(255, 0, 0), width=2)
    doc.close()
    return image


def extract_text_boxes(page: fitz.Page, config: Dict[str, Any]) -> List[Tuple[float, float, float, float]]:
    """Use the engine's textbox extractor when possible; fall back to raw spans."""
    try:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        import pdf_text_replace as engine  # type: ignore

        engine_config = dict(config)
        engine_config.setdefault("_config_dir", ROOT)
        engine_config.setdefault("_warned_fonts", set())
        boxes = engine.extract_textboxes(page, engine_config)
        return [tuple(tb.bbox) for tb in boxes]
    except Exception:
        text_dict = page.get_text("rawdict")
        boxes: List[Tuple[float, float, float, float]] = []
        for block in text_dict.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    if span.get("bbox"):
                        boxes.append(tuple(span["bbox"]))
        return boxes


def make_diff_image(original: Image.Image, processed: Image.Image) -> Image.Image:
    if original.size != processed.size:
        processed = processed.resize(original.size)
    diff = ImageChops.difference(original.convert("RGB"), processed.convert("RGB"))
    return ImageEnhance.Contrast(diff).enhance(6.0)


def pdf_report(pdf_bytes: bytes, config: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], int, int]:
    rows: List[Dict[str, Any]] = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    total_type3 = 0
    total_text_boxes = 0
    for page_index, page in enumerate(doc):
        fonts = page.get_fonts(full=True)
        type3_fonts = [font for font in fonts if len(font) > 2 and str(font[2]).lower() == "type3"]
        text_boxes = extract_text_boxes(page, config)
        total_type3 += len(type3_fonts)
        total_text_boxes += len(text_boxes)
        rows.append(
            {
                "page": page_index + 1,
                "text_boxes": len(text_boxes),
                "type3_fonts": len(type3_fonts),
                "font_types": ", ".join(sorted({str(font[2]) for font in fonts if len(font) > 2})) or "none",
            }
        )
    doc.close()
    return rows, total_type3, total_text_boxes


def run_engine(input_pdf: Path, output_pdf: Path, config_path: Path) -> Tuple[int, str]:
    cmd = [
        sys.executable,
        str(ENGINE),
        "--input",
        str(input_pdf),
        "--output",
        str(output_pdf),
        "--config",
        str(config_path),
    ]
    result = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    logs = "\n".join(part for part in [result.stdout, result.stderr] if part)
    return result.returncode, logs.strip()


def build_config_ui(initial: Dict[str, Any], font_upload_dir: Path) -> Dict[str, Any]:
    preset_name = st.selectbox("Workflow preset", list(PRESETS.keys()), index=0)
    config = dict(initial)
    config.update(PRESETS[preset_name])

    erase_tab, text_tab, review_tab = st.tabs(["1. Erasing", "2. Text adding", "3. Review behavior"])

    with erase_tab:
        st.write("Control how the old PDF text is covered. These settings mainly affect background matching and frame protection.")
        col1, col2 = st.columns(2)
        with col1:
            config["dpi"] = st.slider("Processing DPI", 120, 600, int(config["dpi"]), 10)
            config["background_sample_ring"] = st.slider(
                "Background sample ring (px)", 1, 20, int(config["background_sample_ring"]), 1
            )
            config["background_histogram_step"] = st.slider(
                "Background histogram step", 1, 32, int(config["background_histogram_step"]), 1
            )
            config["foreground_tolerance"] = st.slider(
                "Foreground tolerance", 1, 80, int(config["foreground_tolerance"]), 1
            )
            config["tight_box_padding_px"] = st.slider(
                "Erase box padding (px)", 0, 10, int(config["tight_box_padding_px"]), 1
            )
        with col2:
            config["char_box_margin_px"] = st.slider(
                "Character box margin (px)", 0, 8, int(config["char_box_margin_px"]), 1
            )
            config["line_boundary_search_px"] = st.slider(
                "Line boundary search (px)", 0, 120, int(config["line_boundary_search_px"]), 5
            )
            config["line_boundary_margin_px"] = st.slider(
                "Line boundary margin (px)", 0, 10, int(config["line_boundary_margin_px"]), 1
            )
            config["page_line_safety_px"] = st.slider(
                "Page line safety (px)", 0, 8, int(config["page_line_safety_px"]), 1
            )
            config["char_probe_shrink_ratio"] = st.slider(
                "Character probe shrink ratio", 0.0, 0.45, float(config["char_probe_shrink_ratio"]), 0.01
            )

        st.write("Frame and table-line detection")
        col3, col4 = st.columns(2)
        with col3:
            config["thin_component_thickness_px"] = st.slider(
                "Thin line max thickness (px)", 1, 10, int(config["thin_component_thickness_px"]), 1
            )
            config["thin_component_span_ratio"] = st.slider(
                "Thin line span ratio", 0.01, 1.0, float(config["thin_component_span_ratio"]), 0.01
            )
            config["min_foreground_component_px"] = st.slider(
                "Min foreground component (px)", 1, 50, int(config["min_foreground_component_px"]), 1
            )
        with col4:
            config["page_line_axis_tolerance_pt"] = st.slider(
                "Page line axis tolerance (pt)", 0.05, 2.0, float(config["page_line_axis_tolerance_pt"]), 0.05
            )
            config["page_line_merge_tolerance_pt"] = st.slider(
                "Page line merge tolerance (pt)", 0.1, 5.0, float(config["page_line_merge_tolerance_pt"]), 0.1
            )
            config["page_line_min_span_pt"] = st.slider(
                "Page line min span (pt)", 1.0, 50.0, float(config["page_line_min_span_pt"]), 1.0
            )

    with text_tab:
        st.write("Control how the text is written back after covering the original glyphs.")
        font_mode = st.radio(
            "Font mode",
            ["auto/original", "built-in font name", "font file path", "upload TTF/OTF"],
            horizontal=True,
        )
        if font_mode == "auto/original":
            config["font_family"] = "auto"
        elif font_mode == "built-in font name":
            config["font_family"] = st.text_input("PyMuPDF built-in font name", value="helv")
        elif font_mode == "font file path":
            config["font_family"] = st.text_input(
                "TTF/OTF font path", value=str(config.get("font_family") or "")
            )
        else:
            uploaded_font = st.file_uploader("Upload a TTF/OTF font", type=["ttf", "otf"])
            if uploaded_font is not None:
                font_path = font_upload_dir / safe_filename(uploaded_font.name, "uploaded_font.ttf")
                font_path.write_bytes(uploaded_font.getvalue())
                config["font_family"] = str(font_path)
                st.caption(f"Using uploaded font: {font_path.name}")
            else:
                config["font_family"] = "auto"

        use_auto_size = st.checkbox("Use original font size when possible", value=config.get("font_size") is None)
        if use_auto_size:
            config["font_size"] = None
        else:
            config["font_size"] = st.number_input("Fixed font size (pt)", min_value=1.0, max_value=72.0, value=10.0, step=0.5)
        config["fill_color"] = st.color_picker("Text color", value=str(config.get("fill_color") or "#333333"))
        config["merge_threshold_pt"] = st.slider(
            "Span merge threshold (pt)", 0.0, 10.0, float(config["merge_threshold_pt"]), 0.1
        )

    with review_tab:
        st.write("These controls do not change the engine directly; they help you inspect whether manual repair is still needed.")
        st.markdown(
            "- Use text-box overlay to check whether the detected spans match the visible text.\n"
            "- Use the difference view to find unexpected patches, missing glyphs, or broken frame lines.\n"
            "- Export the generated YAML after a successful run so the same settings can be reused from CLI."
        )

    return config


def main() -> None:
    st.set_page_config(page_title="Type-3 Font Eraser UI", layout="wide")
    st.title("Type-3 Font Eraser UI")
    st.caption("Local two-page comparison interface for PDF erasing and text re-adding.")

    if not ENGINE.exists():
        st.error("pdf_text_replace.py was not found. Run this UI from the repository root.")
        st.stop()

    uploaded_pdf = st.file_uploader("Input PDF", type=["pdf"])
    initial_config = load_yaml_config(DEFAULT_CONFIG)

    with tempfile.TemporaryDirectory(prefix="type3_ui_") as tmpdir:
        tmp_path = Path(tmpdir)
        config = build_config_ui(initial_config, tmp_path)
        config_text = dump_yaml(config)

        st.divider()
        left, right = st.columns([0.35, 0.65])

        with left:
            st.subheader("Run")
            output_name = st.text_input("Output file name", value="output_ui.pdf")
            run_button = st.button("Run PDF processing", type="primary", disabled=uploaded_pdf is None)
            st.download_button(
                "Download generated config.yaml",
                data=config_text.encode("utf-8"),
                file_name="ui_config.yaml",
                mime="text/yaml",
            )

            if uploaded_pdf is not None:
                input_bytes = uploaded_pdf.getvalue()
                report_rows, type3_count, text_box_count = pdf_report(input_bytes, config)
                st.metric("Pages", len(report_rows))
                st.metric("Type 3 font entries", type3_count)
                st.metric("Detected text boxes", text_box_count)
                with st.expander("Page diagnosis", expanded=False):
                    st.dataframe(report_rows, use_container_width=True, hide_index=True)
            else:
                input_bytes = b""

            if run_button and uploaded_pdf is not None:
                input_path = tmp_path / safe_filename(uploaded_pdf.name, "input.pdf")
                output_path = tmp_path / safe_filename(output_name, "output_ui.pdf")
                config_path = tmp_path / "ui_config.yaml"
                input_path.write_bytes(input_bytes)
                config_path.write_text(config_text, encoding="utf-8")

                return_code, logs = run_engine(input_path, output_path, config_path)
                st.session_state["last_logs"] = logs
                st.session_state["last_return_code"] = return_code
                st.session_state["last_output_name"] = output_path.name
                st.session_state["last_input_pdf"] = input_bytes
                st.session_state["last_config"] = config
                if return_code == 0 and output_path.exists():
                    st.session_state["last_output_pdf"] = output_path.read_bytes()
                    st.success("Processing completed.")
                else:
                    st.session_state.pop("last_output_pdf", None)
                    st.error("Processing failed. Check the logs below.")

            if "last_output_pdf" in st.session_state:
                st.download_button(
                    "Download processed PDF",
                    data=st.session_state["last_output_pdf"],
                    file_name=st.session_state.get("last_output_name", "output_ui.pdf"),
                    mime="application/pdf",
                )

            with st.expander("Engine logs", expanded=False):
                st.code(st.session_state.get("last_logs", "No run yet."), language="text")

        with right:
            st.subheader("Side-by-side review")
            source_pdf = st.session_state.get("last_input_pdf") or input_bytes
            processed_pdf = st.session_state.get("last_output_pdf")
            if not source_pdf:
                st.info("Upload a PDF to preview pages. Run processing to compare original and output.")
            else:
                doc = fitz.open(stream=source_pdf, filetype="pdf")
                page_count = len(doc)
                doc.close()
                col_a, col_b, col_c = st.columns(3)
                with col_a:
                    page_no = st.number_input("Page", min_value=1, max_value=max(page_count, 1), value=1, step=1)
                with col_b:
                    preview_dpi = st.slider("Preview DPI", 72, 220, 120, 10)
                with col_c:
                    draw_boxes = st.checkbox("Show detected text boxes", value=False)

                page_index = int(page_no) - 1
                original_img = render_page(source_pdf, page_index, preview_dpi, draw_boxes, config)
                if processed_pdf:
                    processed_img = render_page(processed_pdf, page_index, preview_dpi, draw_boxes, config)
                    c1, c2 = st.columns(2)
                    with c1:
                        st.image(original_img, caption="Original", use_container_width=True)
                    with c2:
                        st.image(processed_img, caption="Processed", use_container_width=True)
                    if st.checkbox("Show amplified difference", value=False):
                        st.image(make_diff_image(original_img, processed_img), caption="Amplified difference", use_container_width=True)
                else:
                    st.image(original_img, caption="Original preview", use_container_width=True)

        st.divider()
        st.subheader("Manual repair checklist")
        st.dataframe(MANUAL_REVIEW_ITEMS, use_container_width=True, hide_index=True)
        with st.expander("Current generated YAML", expanded=False):
            st.code(config_text, language="yaml")


if __name__ == "__main__":
    main()

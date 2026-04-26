#!/usr/bin/env python3
"""Tkinter UI for pdf_text_replace.py with side-by-side PDF comparison."""
from __future__ import annotations

import subprocess
import sys
import threading
import traceback
from pathlib import Path
from typing import Any, Dict, Optional

import fitz
from PIL import Image, ImageTk
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import yaml

APP_TITLE = "Type-3 Font Eraser UI"
DEFAULTS: Dict[str, Any] = {
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

HELP_TEXT = """Manual review checklist:
- Erase damages figure/table lines: reduce padding/margins or increase line safety.
- Erase misses glyph edges: increase char margin or foreground tolerance.
- Patch color is visible: raise DPI or adjust background sampling ring.
- Rewritten text overflows: use auto/original size, reduce fixed size, or select a narrower font.
- Wrong glyphs or Type 3 remains: choose a real TTF/OTF font covering the PDF characters.
- Scanned/raster text is not editable as spans; use OCR or manual PDF editing first.
"""


class PreviewPane(ttk.Frame):
    def __init__(self, master: tk.Misc, title: str) -> None:
        super().__init__(master)
        self.doc: Optional[fitz.Document] = None
        self.photo: Optional[ImageTk.PhotoImage] = None
        top = ttk.Frame(self)
        top.pack(fill="x", padx=4, pady=(4, 2))
        ttk.Label(top, text=title, font=("TkDefaultFont", 10, "bold")).pack(side="left")
        self.meta = ttk.Label(top, text="No PDF loaded")
        self.meta.pack(side="right")
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(frame, bg="#f2f2f2", highlightthickness=1, highlightbackground="#bbbbbb")
        ybar = ttk.Scrollbar(frame, orient="vertical", command=self.canvas.yview)
        xbar = ttk.Scrollbar(frame, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

    def load(self, path: Optional[Path]) -> None:
        self.close()
        if path and path.exists():
            self.doc = fitz.open(path)
            self.meta.configure(text=f"{len(self.doc)} pages")
        else:
            self.meta.configure(text="No PDF loaded")
        self.canvas.delete("all")
        self.photo = None

    def close(self) -> None:
        if self.doc is not None:
            self.doc.close()
        self.doc = None
        self.photo = None

    @property
    def page_count(self) -> int:
        return len(self.doc) if self.doc is not None else 0

    def render(self, page_index: int, zoom: float) -> None:
        self.canvas.delete("all")
        self.photo = None
        if self.doc is None:
            self.canvas.create_text(24, 24, anchor="nw", text="No PDF loaded", fill="#666")
            self.canvas.configure(scrollregion=(0, 0, 400, 300))
            return
        if page_index < 0 or page_index >= len(self.doc):
            self.canvas.create_text(24, 24, anchor="nw", text="Page out of range", fill="#666")
            return
        pix = self.doc[page_index].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        self.photo = ImageTk.PhotoImage(img)
        self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
        self.canvas.configure(scrollregion=(0, 0, pix.width, pix.height))


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1320x860")
        self.minsize(1080, 720)
        self.repo_dir = Path(__file__).resolve().parent
        self.script = self.repo_dir / "pdf_text_replace.py"
        self.input_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self.config_path = tk.StringVar(value=str(self.repo_dir / "config.yaml"))
        self.page = tk.IntVar(value=1)
        self.zoom = tk.DoubleVar(value=1.4)
        self.status = tk.StringVar(value="Ready")
        self.vars: Dict[str, tk.Variable] = {}
        for key, value in DEFAULTS.items():
            if value is None:
                self.vars[key] = tk.StringVar(value="auto")
            elif isinstance(value, int):
                self.vars[key] = tk.IntVar(value=value)
            elif isinstance(value, float):
                self.vars[key] = tk.DoubleVar(value=value)
            else:
                self.vars[key] = tk.StringVar(value=str(value))
        self._build()
        self._load_config(Path(self.config_path.get()), quiet=True)

    def _build(self) -> None:
        top = ttk.Frame(self, padding=8)
        top.pack(side="top", fill="x")
        self._path_row(top, 0, "Input PDF", self.input_path, self.choose_input)
        self._path_row(top, 1, "Output PDF", self.output_path, self.choose_output)
        self._path_row(top, 2, "Config YAML", self.config_path, self.load_config_dialog, "Load")
        top.columnconfigure(1, weight=1)

        body = ttk.PanedWindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        settings = ttk.Frame(body, width=360)
        preview = ttk.Frame(body)
        body.add(settings, weight=0)
        body.add(preview, weight=1)
        self._settings(settings)
        self._preview(preview)
        ttk.Label(self, textvariable=self.status, padding=(8, 4)).pack(side="bottom", fill="x")

    def _path_row(self, parent: ttk.Frame, row: int, label: str, var: tk.StringVar, cmd, text: str = "Browse") -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w")
        ttk.Entry(parent, textvariable=var).grid(row=row, column=1, sticky="ew", padx=5, pady=2)
        ttk.Button(parent, text=text, command=cmd).grid(row=row, column=2, padx=3)

    def _settings(self, parent: ttk.Frame) -> None:
        nb = ttk.Notebook(parent)
        nb.pack(fill="both", expand=True)
        erase = ttk.Frame(nb, padding=8)
        text = ttk.Frame(nb, padding=8)
        run = ttk.Frame(nb, padding=8)
        nb.add(erase, text="1 Erase")
        nb.add(text, text="2 Text")
        nb.add(run, text="Run / diagnose")

        self._note(erase, "Tune the coverage step: background sampling, glyph detection, padding, and frame-line protection.", grid=True)
        erase_fields = [
            ("DPI", "dpi"),
            ("Span merge threshold pt", "merge_threshold_pt"),
            ("Background ring px", "background_sample_ring"),
            ("Background histogram step", "background_histogram_step"),
            ("Foreground tolerance", "foreground_tolerance"),
            ("Tight box padding px", "tight_box_padding_px"),
            ("Character box margin px", "char_box_margin_px"),
            ("Thin line thickness px", "thin_component_thickness_px"),
            ("Thin line span ratio", "thin_component_span_ratio"),
            ("Line boundary search px", "line_boundary_search_px"),
            ("Line boundary margin px", "line_boundary_margin_px"),
            ("Char probe shrink ratio", "char_probe_shrink_ratio"),
            ("Page line safety px", "page_line_safety_px"),
        ]
        for row, (label, key) in enumerate(erase_fields, start=1):
            self._field(erase, row, label, key)

        self._note(text, "Tune replacement text: font, fixed/auto size, and color. Use a TTF/OTF font to reduce Type 3 fallback.", grid=True)
        self._field(text, 1, "Font family / TTF path", "font_family", font_button=True)
        self._field(text, 2, "Font size", "font_size")
        self._field(text, 3, "Text color", "fill_color")
        ttk.Label(text, text="Font size accepts auto/null or a fixed pt value.", wraplength=330).grid(row=4, column=0, columnspan=3, sticky="w", pady=(8, 0))

        self._note(run, HELP_TEXT, grid=False)
        ttk.Button(run, text="Save current config", command=self.save_config_dialog).pack(fill="x", pady=4)
        ttk.Button(run, text="Copy command", command=self.copy_command).pack(fill="x", pady=4)
        self.run_button = ttk.Button(run, text="Run processing", command=self.run_processing)
        self.run_button.pack(fill="x", pady=(16, 4))
        ttk.Button(run, text="Reload previews", command=self.reload_previews).pack(fill="x", pady=4)

    def _note(self, parent: ttk.Frame, text: str, grid: bool) -> None:
        label = ttk.Label(parent, text=text, wraplength=330, justify="left")
        if grid:
            label.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        else:
            label.pack(anchor="w", fill="x", pady=(0, 10))

    def _field(self, parent: ttk.Frame, row: int, label: str, key: str, font_button: bool = False) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3)
        ttk.Entry(parent, textvariable=self.vars[key]).grid(row=row, column=1, sticky="ew", padx=4, pady=3)
        if font_button:
            ttk.Button(parent, text="...", width=3, command=self.choose_font).grid(row=row, column=2)
        parent.columnconfigure(1, weight=1)

    def _preview(self, parent: ttk.Frame) -> None:
        toolbar = ttk.Frame(parent)
        toolbar.pack(side="top", fill="x", pady=(0, 5))
        ttk.Label(toolbar, text="Page").pack(side="left")
        ttk.Spinbox(toolbar, from_=1, to=9999, width=6, textvariable=self.page, command=self.render_previews).pack(side="left", padx=4)
        ttk.Label(toolbar, text="Zoom").pack(side="left", padx=(12, 0))
        ttk.Scale(toolbar, from_=0.5, to=3.0, orient="horizontal", variable=self.zoom, command=lambda _v: self.render_previews()).pack(side="left", fill="x", expand=True, padx=5)
        ttk.Button(toolbar, text="Previous", command=lambda: self.shift_page(-1)).pack(side="left", padx=2)
        ttk.Button(toolbar, text="Next", command=lambda: self.shift_page(1)).pack(side="left", padx=2)
        panes = ttk.PanedWindow(parent, orient="horizontal")
        panes.pack(fill="both", expand=True)
        self.left = PreviewPane(panes, "Original")
        self.right = PreviewPane(panes, "Processed")
        panes.add(self.left, weight=1)
        panes.add(self.right, weight=1)

    def choose_input(self) -> None:
        name = filedialog.askopenfilename(title="Choose input PDF", filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")])
        if not name:
            return
        self.input_path.set(name)
        path = Path(name)
        if not self.output_path.get():
            self.output_path.set(str(path.with_name(f"{path.stem}_type3_fixed.pdf")))
        self.reload_previews()

    def choose_output(self) -> None:
        name = filedialog.asksaveasfilename(title="Choose output PDF", defaultextension=".pdf", filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")])
        if name:
            self.output_path.set(name)
            self.reload_previews()

    def choose_font(self) -> None:
        name = filedialog.askopenfilename(title="Choose font", filetypes=[("Font files", "*.ttf *.otf"), ("All files", "*.*")])
        if name:
            self.vars["font_family"].set(name)

    def load_config_dialog(self) -> None:
        path = self.config_path.get().strip() or filedialog.askopenfilename(title="Choose config YAML", filetypes=[("YAML", "*.yaml *.yml"), ("All files", "*.*")])
        if path:
            self.config_path.set(path)
            self._load_config(Path(path), quiet=False)

    def _load_config(self, path: Path, quiet: bool) -> None:
        if not path.exists():
            return
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            for key, value in data.items():
                if key in self.vars:
                    self.vars[key].set("auto" if value is None else value)
            if not quiet:
                self.status.set(f"Loaded config: {path}")
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Failed to load config:\n{exc}")

    def collect_config(self) -> Dict[str, Any]:
        config: Dict[str, Any] = {}
        for key, default in DEFAULTS.items():
            raw = str(self.vars[key].get()).strip()
            if key == "font_size":
                config[key] = None if raw.lower() in {"", "auto", "none", "null"} else float(raw)
            elif isinstance(default, int):
                config[key] = int(float(raw))
            elif isinstance(default, float):
                config[key] = float(raw)
            else:
                config[key] = raw
        return config

    def save_config_dialog(self) -> None:
        name = filedialog.asksaveasfilename(title="Save config YAML", defaultextension=".yaml", filetypes=[("YAML", "*.yaml *.yml"), ("All files", "*.*")])
        if not name:
            return
        Path(name).write_text(yaml.safe_dump(self.collect_config(), sort_keys=False, allow_unicode=True), encoding="utf-8")
        self.config_path.set(name)
        self.status.set(f"Saved config: {name}")

    def temp_config(self) -> Path:
        out = Path(self.output_path.get()).expanduser()
        parent = out.parent if out.parent.exists() else Path.cwd()
        return parent / ".type3_font_eraser_ui_config.yaml"

    def command(self, cfg: Path) -> list[str]:
        return [sys.executable, str(self.script), "--input", str(Path(self.input_path.get()).expanduser()), "--output", str(Path(self.output_path.get()).expanduser()), "--config", str(cfg)]

    def copy_command(self) -> None:
        cfg = self.temp_config()
        cmd = " ".join(f'"{p}"' if " " in p else p for p in self.command(cfg))
        self.clipboard_clear()
        self.clipboard_append(cmd)
        self.status.set("Command copied. Run once or save config to create the YAML file.")

    def run_processing(self) -> None:
        try:
            self._validate_inputs()
            cfg = self.temp_config()
            cfg.write_text(yaml.safe_dump(self.collect_config(), sort_keys=False, allow_unicode=True), encoding="utf-8")
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Cannot start processing:\n{exc}")
            return
        self.run_button.configure(state="disabled")
        self.status.set("Processing PDF...")
        threading.Thread(target=self._worker, args=(cfg,), daemon=True).start()

    def _validate_inputs(self) -> None:
        if not self.script.exists():
            raise FileNotFoundError(f"Missing script: {self.script}")
        in_pdf = Path(self.input_path.get()).expanduser()
        if not in_pdf.exists() or in_pdf.suffix.lower() != ".pdf":
            raise ValueError("Choose a valid input PDF.")
        out_pdf = Path(self.output_path.get()).expanduser()
        if not out_pdf.name:
            raise ValueError("Choose an output PDF path.")
        out_pdf.parent.mkdir(parents=True, exist_ok=True)

    def _worker(self, cfg: Path) -> None:
        try:
            result = subprocess.run(self.command(cfg), cwd=str(self.repo_dir), capture_output=True, text=True, check=False)
            if result.returncode != 0:
                raise RuntimeError((result.stderr or result.stdout or "No output").strip())
            summary = self.validate_output(Path(self.output_path.get()).expanduser())
            self.after(0, lambda: self._done(summary))
        except Exception:
            err = traceback.format_exc()
            self.after(0, lambda: self._failed(err))

    def _done(self, summary: str) -> None:
        self.run_button.configure(state="normal")
        self.status.set(f"Done. {summary}")
        self.reload_previews()

    def _failed(self, err: str) -> None:
        self.run_button.configure(state="normal")
        self.status.set("Processing failed")
        messagebox.showerror(APP_TITLE, err)

    def validate_output(self, path: Path) -> str:
        if not path.exists():
            return "Output file was not created."
        with fitz.open(path) as doc:
            pages, count = [], 0
            for i, page in enumerate(doc):
                type3 = [f for f in page.get_fonts(full=True) if str(f[2]).lower() == "type3"]
                if type3:
                    pages.append(i + 1)
                    count += len(type3)
        if count:
            return f"Output saved; Type 3 fonts still detected: {count} on page(s) {pages[:10]}."
        return "Output saved; no Type 3 fonts detected by PyMuPDF."

    def reload_previews(self) -> None:
        try:
            inp = Path(self.input_path.get()).expanduser() if self.input_path.get() else None
            out = Path(self.output_path.get()).expanduser() if self.output_path.get() else None
            self.left.load(inp)
            self.right.load(out)
            max_pages = max(self.left.page_count, self.right.page_count, 1)
            self.page.set(min(max(self.page.get(), 1), max_pages))
            self.render_previews()
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Preview failed:\n{exc}")

    def render_previews(self) -> None:
        try:
            idx = max(self.page.get() - 1, 0)
            z = float(self.zoom.get())
            self.left.render(idx, z)
            self.right.render(idx, z)
        except Exception as exc:
            self.status.set(f"Preview error: {exc}")

    def shift_page(self, delta: int) -> None:
        max_pages = max(self.left.page_count, self.right.page_count, 1)
        self.page.set(min(max(self.page.get() + delta, 1), max_pages))
        self.render_previews()

    def destroy(self) -> None:
        if hasattr(self, "left"):
            self.left.close()
            self.right.close()
        super().destroy()


def main() -> int:
    app = App()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

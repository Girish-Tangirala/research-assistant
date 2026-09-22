"""A scrollable PDF viewer for Tk, rendered with PDFium on a background thread.

Pages are rendered lazily (only those near the viewport) and far-away pages are
dropped again, so long papers stay light. Reloading a PDF keeps the scroll
position, like Overleaf's preview. Changed pages can be outlined. Clicks are
reported in PDF points (top-left origin) so they can be mapped to the source.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from typing import Any

import customtkinter as ctk

from core.preview import PDFIUM_LOCK

PAGE_GAP = 14
MARGIN = 12
KEEP_AROUND = 3          # pages rendered above/below the viewport
HIGHLIGHT = "#f0883e"
MARK = "#58a6ff"
BACKGROUND = "#3b3f45"
ZOOM_STEPS = (0.5, 0.67, 0.8, 1.0, 1.25, 1.5, 2.0, 3.0)


class _RenderWorker(threading.Thread):
    """Renders (generation, page, scale) jobs; stale generations are skipped."""

    def __init__(self) -> None:
        super().__init__(daemon=True, name="pdf-render")
        self.jobs: queue.Queue = queue.Queue()
        self.results: queue.Queue = queue.Queue()
        self.latest = 0
        self._doc: Any = None
        self._doc_gen = -1

    def run(self) -> None:
        import pypdfium2 as pdfium

        while True:
            job = self.jobs.get()
            if job is None:
                break
            gen, data, page_index, scale = job
            if gen != self.latest:
                continue
            try:
                with PDFIUM_LOCK:
                    if self._doc_gen != gen:
                        if self._doc is not None:
                            self._doc.close()
                        self._doc, self._doc_gen = pdfium.PdfDocument(data), gen
                    page = self._doc[page_index]
                    image = page.render(scale=scale).to_pil()
                    page.close()
                self.results.put((gen, page_index, scale, image))
            except Exception as exc:  # noqa: BLE001 - report and keep the worker alive
                self.results.put((gen, page_index, scale, exc))


class PdfViewer(ctk.CTkFrame):
    """Canvas-based viewer: ``load(path)``, zoom, page navigation, change highlights."""

    def __init__(self, master: Any, on_page_change: Any = None, on_click: Any = None) -> None:
        super().__init__(master, fg_color=BACKGROUND, corner_radius=6)
        self.on_page_change = on_page_change
        self.on_click = on_click  # (page, x_pt, y_pt, x_root, y_root, context_menu) -> None
        self.clickable = True
        self.canvas = tk.Canvas(self, bg=BACKGROUND, highlightthickness=0, bd=0)
        self.scroll = ctk.CTkScrollbar(self, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self._on_yscroll)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scroll.grid(row=0, column=1, sticky="ns")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        for widget in (self.canvas,):
            widget.bind("<MouseWheel>", self._on_wheel)
            widget.bind("<Button-4>", lambda e: self.canvas.yview_scroll(-3, "units"))
            widget.bind("<Button-5>", lambda e: self.canvas.yview_scroll(3, "units"))
        self.canvas.bind("<Configure>", lambda _e: self._schedule_layout())
        self.canvas.bind("<ButtonRelease-1>", lambda e: self._clicked(e, False))
        self.canvas.bind("<Button-3>", lambda e: self._clicked(e, True))
        self.canvas.bind("<Motion>", self._on_motion)

        self.data: bytes | None = None
        self.path: Path | None = None
        self.sizes: list[tuple[float, float]] = []
        self.tops: list[int] = []
        self.scale = 1.0
        self.zoom: float | None = None  # None = fit width
        self.highlight: set[int] = set()
        self.photos: dict[int, Any] = {}
        self.pending: set[int] = set()
        self.gen = 0
        self._layout_job: str | None = None
        self.worker = _RenderWorker()
        self.worker.start()
        self.after(40, self._poll)
        self.message("No PDF yet - click Recompile.")

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    @property
    def page_count(self) -> int:
        return len(self.sizes)

    def message(self, text: str) -> None:
        self.canvas.delete("all")
        self.photos.clear()
        self.canvas.create_text(20, 20, text=text, anchor="nw", fill="#c9d1d9", font=("Segoe UI", 11), width=420)
        self.canvas.configure(scrollregion=(0, 0, 1, 1))

    def load(self, path: Path, highlight: set[int] | None = None, keep_position: bool = True) -> None:
        """Show ``path``; the file is read into memory so it can be rebuilt while displayed."""
        import pypdfium2 as pdfium

        data = path.read_bytes()
        with PDFIUM_LOCK:
            document = pdfium.PdfDocument(data)
            try:
                sizes = [document.get_page_size(i) for i in range(len(document))]
            finally:
                document.close()
        fraction = self.canvas.yview()[0] if keep_position and self.sizes else 0.0
        self.data, self.path, self.sizes = data, path, sizes
        self.highlight = set(highlight or ())
        self._new_generation()
        self._layout(fraction)

    def jump_to(self, page: int) -> None:
        if 0 <= page < len(self.tops) and self.tops:
            total = self.tops[-1] + self._page_height(len(self.tops) - 1) + MARGIN
            self.canvas.yview_moveto(max(0.0, (self.tops[page] - MARGIN) / total))
            self._ensure_visible()

    def current_page(self) -> int:
        if not self.tops:
            return 0
        y = self.canvas.canvasy(self.canvas.winfo_height() / 3)
        return max((i for i, top in enumerate(self.tops) if top <= y), default=0)

    def set_zoom(self, zoom: float | None) -> None:
        page = self.current_page()
        self.zoom = zoom
        self._new_generation()
        self._layout(0.0)
        self.jump_to(page)

    def zoom_in(self) -> None:
        self.set_zoom(next((z for z in ZOOM_STEPS if z > self.scale * 1.01), ZOOM_STEPS[-1]))

    def zoom_out(self) -> None:
        self.set_zoom(next((z for z in reversed(ZOOM_STEPS) if z < self.scale * 0.99), ZOOM_STEPS[0]))

    def point_at(self, canvas_x: float, canvas_y: float) -> tuple[int, float, float] | None:
        """``(page, x, y)`` in PDF points (top-left origin) for a canvas position, or ``None``."""
        for index, top in enumerate(self.tops):
            coords = self.canvas.coords(f"slot{index}")
            if not coords:
                continue
            left, _top, right, bottom = coords
            if left <= canvas_x <= right and top <= canvas_y <= bottom:
                return index, (canvas_x - left) / self.scale, (canvas_y - top) / self.scale
        return None

    def mark(self, page: int, x: float, y: float) -> None:
        """Briefly show where a click landed."""
        coords = self.canvas.coords(f"slot{page}") if page < len(self.tops) else None
        if not coords:
            return
        cx, cy = coords[0] + x * self.scale, self.tops[page] + y * self.scale
        self.canvas.delete("mark")
        self.canvas.create_oval(cx - 9, cy - 9, cx + 9, cy + 9, outline=MARK, width=3, tags=("mark",))
        self.after(1200, lambda: self.canvas.delete("mark"))

    def _clicked(self, event: tk.Event, context_menu: bool) -> None:
        if self.data is None or self.on_click is None or not (self.clickable or context_menu):
            return
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        hit = self.point_at(x, y)
        if hit is not None:
            self.mark(*hit)
            self.on_click(*hit, event.x_root, event.y_root, context_menu)

    def _on_motion(self, event: tk.Event) -> None:
        over_page = (self.data is not None and self.clickable and self.on_click is not None
                     and self.point_at(self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)) is not None)
        cursor = "hand2" if over_page else ""
        if self.canvas.cget("cursor") != cursor:
            self.canvas.configure(cursor=cursor)

    def destroy(self) -> None:
        self.worker.jobs.put(None)
        super().destroy()

    # ------------------------------------------------------------------ #
    # Layout and rendering
    # ------------------------------------------------------------------ #
    def _new_generation(self) -> None:
        self.gen += 1
        self.worker.latest = self.gen
        self.photos.clear()
        self.pending.clear()

    def _page_height(self, index: int) -> int:
        return int(self.sizes[index][1] * self.scale)

    def _schedule_layout(self) -> None:
        if self.zoom is None and self.sizes:
            if self._layout_job:
                self.after_cancel(self._layout_job)
            self._layout_job = self.after(250, self._relayout_for_width)

    def _relayout_for_width(self) -> None:
        self._layout_job = None
        fraction = self.canvas.yview()[0]
        self._new_generation()
        self._layout(fraction)

    def _layout(self, fraction: float) -> None:
        self.canvas.delete("all")
        if not self.sizes:
            self.message("The PDF has no pages.")
            return
        width = max(self.canvas.winfo_width(), 200)
        widest = max(w for w, _h in self.sizes)
        self.scale = self.zoom if self.zoom is not None else max(0.2, (width - 2 * MARGIN) / widest)
        self.tops, y = [], MARGIN
        content_width = int(widest * self.scale) + 2 * MARGIN
        for index, (w, h) in enumerate(self.sizes):
            self.tops.append(y)
            x = max(MARGIN, (max(width, content_width) - int(w * self.scale)) // 2)
            pw, ph = int(w * self.scale), int(h * self.scale)
            self.canvas.create_rectangle(x, y, x + pw, y + ph, fill="white", outline="", tags=(f"slot{index}",))
            self.canvas.create_text(x + pw // 2, y + ph // 2, text=f"Page {index + 1}", fill="#999",
                                    tags=(f"label{index}",))
            if index in self.highlight:
                self.canvas.create_rectangle(x - 4, y - 4, x + pw + 4, y + ph + 4, outline=HIGHLIGHT, width=3,
                                             tags=("hl",))
                self.canvas.create_text(x + 6, y + 6, text="● changed", anchor="nw", fill=HIGHLIGHT,
                                        font=("Segoe UI", 10, "bold"), tags=("hl",))
            y += ph + PAGE_GAP
        self.canvas.configure(scrollregion=(0, 0, max(width, content_width), y + MARGIN))
        self.canvas.yview_moveto(fraction)
        self._ensure_visible()

    def _visible_range(self) -> range:
        top = self.canvas.canvasy(0)
        bottom = top + self.canvas.winfo_height()
        visible = [i for i, t in enumerate(self.tops) if t <= bottom and t + self._page_height(i) >= top]
        if not visible:
            return range(0, min(1, len(self.tops)))
        return range(max(0, visible[0] - KEEP_AROUND), min(len(self.tops), visible[-1] + KEEP_AROUND + 1))

    def _ensure_visible(self) -> None:
        if self.data is None:
            return
        wanted = self._visible_range()
        for index in list(self.photos):
            if index not in wanted:
                self.canvas.delete(f"img{index}")
                del self.photos[index]
        for index in wanted:
            if index not in self.photos and index not in self.pending:
                self.pending.add(index)
                self.worker.jobs.put((self.gen, self.data, index, self.scale))
        if self.on_page_change:
            self.on_page_change(self.current_page() + 1, self.page_count)

    def _poll(self) -> None:
        from PIL import ImageTk

        try:
            while True:
                gen, index, scale, image = self.worker.results.get_nowait()
                if gen != self.gen or scale != self.scale:
                    continue
                self.pending.discard(index)
                if isinstance(image, Exception) or index not in self._visible_range():
                    continue
                photo = ImageTk.PhotoImage(image)
                self.photos[index] = photo
                x = self.canvas.coords(f"slot{index}")[0]
                self.canvas.delete(f"label{index}")
                self.canvas.create_image(x, self.tops[index], image=photo, anchor="nw", tags=(f"img{index}",))
                self.canvas.tag_raise("hl")
                self.canvas.tag_raise("mark")
        except queue.Empty:
            pass
        finally:
            if self.winfo_exists():
                self.after(40, self._poll)

    def _on_yscroll(self, first: str, last: str) -> None:
        self.scroll.set(first, last)
        self._ensure_visible()

    def _on_wheel(self, event: tk.Event) -> None:
        if event.state & 0x4:  # Ctrl + wheel = zoom
            (self.zoom_in if event.delta > 0 else self.zoom_out)()
            return
        self.canvas.yview_scroll(int(-event.delta / 40), "units")

"""Figure handling: validating image files, placing them in the repository and
building ``figure`` environments.

Images are chosen by the user from anywhere on the computer; they are copied
into the paper's graphics folder only after approval. Formats pdfLaTeX cannot
include (TIFF, BMP, GIF, WebP) are converted to PNG with Pillow; vector formats
that need external tools (SVG, EPS) are rejected with an explanation.
"""

from __future__ import annotations

import base64
import io
import re
from pathlib import Path, PurePosixPath

from core.latex_parser import comment_mask, split_sections, strip_comments

INCLUDABLE = {".png", ".jpg", ".jpeg", ".pdf"}
CONVERTIBLE = {".tif", ".tiff", ".bmp", ".gif", ".webp"}
NEEDS_EXPORT = {".svg": "Export it as PDF (e.g. from Inkscape or Illustrator) first.",
                ".eps": "Convert it to PDF first (e.g. with epstopdf), or export a PDF from the source tool.",
                ".emf": "Export it as PDF or PNG first.", ".wmf": "Export it as PDF or PNG first."}
MAX_FILE_MB = 50          # Overleaf's per-file upload limit
WARN_FILE_MB = 10
VISION_MAX_BYTES = 3_750_000
VISION_MAX_SIDE = 1568
COMMON_GRAPHICS_DIRS = ("figures", "figs", "images", "img", "graphics", "pictures", "plots")
_GRAPHICSPATH_RE = re.compile(r"\\graphicspath\s*\{\s*\{([^}]*)\}")
_GRAPHICX_RE = re.compile(r"\\usepackage(?:\[[^\]]*\])?\{[^}]*\bgraphicx?\b[^}]*\}")
_LABEL_RE = re.compile(r"\\label\{([^}]*)\}")


class FigureError(ValueError):
    """An image cannot be added (unsupported, too large, missing)."""


def check_image(path: Path) -> list[str]:
    """Validate a user-selected image. Returns warnings; raises on hard errors."""
    if not path.is_file():
        raise FigureError(f"File not found: {path}")
    suffix = path.suffix.lower()
    if suffix in NEEDS_EXPORT:
        raise FigureError(f"{path.name}: {suffix} files cannot be included directly. {NEEDS_EXPORT[suffix]}")
    if suffix not in INCLUDABLE | CONVERTIBLE:
        raise FigureError(f"{path.name}: unsupported image type {suffix or '(none)'} - use PNG, JPG or PDF.")
    size_mb = path.stat().st_size / 1_048_576
    if size_mb > MAX_FILE_MB:
        raise FigureError(f"{path.name} is {size_mb:.0f} MB - Overleaf accepts files up to {MAX_FILE_MB} MB.")
    warnings = []
    if size_mb > WARN_FILE_MB:
        warnings.append(f"{path.name} is {size_mb:.0f} MB; consider compressing it to keep the project fast.")
    if suffix in CONVERTIBLE:
        warnings.append(f"{path.name} will be converted to PNG (pdfLaTeX cannot include {suffix} files).")
    return warnings


def convert_to_png(source: Path, work_dir: Path) -> Path:
    """Convert a TIFF/BMP/GIF/WebP image to PNG in ``work_dir``."""
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - pillow is a runtime dependency
        raise FigureError("Pillow is required to convert images (pip install pillow).") from exc
    work_dir.mkdir(parents=True, exist_ok=True)
    target = work_dir / f"{source.stem}.png"
    with Image.open(source) as image:
        image.seek(0)
        image.convert("RGBA" if image.mode in ("RGBA", "LA", "P") else "RGB").save(target, "PNG")
    return target


def safe_stem(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-_").lower()
    return stem or "figure"


def graphics_dir(root: Path, main_tex_source: str) -> str:
    """Folder (repo-relative, POSIX) where new images should go."""
    match = _GRAPHICSPATH_RE.search(strip_comments(main_tex_source))
    if match and match.group(1).strip() and not match.group(1).strip().startswith(("/", "..")):
        return match.group(1).strip().strip("/").removeprefix("./") or "figures"
    # Use the folder's real spelling: Windows is case-insensitive, Git/Overleaf are not.
    existing = {p.name.lower(): p.name for p in root.iterdir() if p.is_dir()} if root.is_dir() else {}
    for name in COMMON_GRAPHICS_DIRS:
        if name in existing:
            return existing[name]
    return "figures"


def unique_rel_path(root: Path, folder: str, stem: str, suffix: str, taken: set[str]) -> str:
    """Repo-relative destination that neither exists nor was already planned."""
    for n in range(1, 1000):
        name = f"{stem}{'' if n == 1 else f'-{n}'}{suffix}"
        rel = str(PurePosixPath(folder) / name) if folder else name
        if rel not in taken and not (root / rel).exists():
            taken.add(rel)
            return rel
    raise FigureError(f"Could not find a free file name for {stem}{suffix}")


def unique_label(stem: str, tex_sources: list[str], taken: set[str]) -> str:
    existing = {m.group(1) for src in tex_sources for m in _LABEL_RE.finditer(src)} | taken
    label, n = f"fig:{stem}", 2
    while label in existing:
        label, n = f"fig:{stem}-{n}", n + 1
    taken.add(label)
    return label


def include_path(asset_rel: str, main_tex_rel: str) -> str:
    """Path for ``\\includegraphics`` relative to the main file's folder (where LaTeX runs)."""
    main_dir = PurePosixPath(main_tex_rel).parent
    asset = PurePosixPath(asset_rel)
    try:
        return str(asset.relative_to(main_dir)) if str(main_dir) != "." else str(asset)
    except ValueError:
        return "../" * len(main_dir.parts) + str(asset)


def figure_block(path: str, caption: str, label: str, width: str = r"0.8\linewidth",
                 placement: str = "htbp") -> str:
    return (f"\\begin{{figure}}[{placement}]\n"
            f"  \\centering\n"
            f"  \\includegraphics[width={width}]{{{path}}}\n"
            f"  \\caption{{{caption.strip()}}}\n"
            f"  \\label{{{label}}}\n"
            f"\\end{{figure}}")


def ensure_graphicx(main_source: str) -> str | None:
    """Return the preamble with ``\\usepackage{graphicx}`` added, or ``None`` if present."""
    if _GRAPHICX_RE.search(strip_comments(main_source)):
        return None
    mask = comment_mask(main_source)
    begin = main_source.find("\\begin{document}")
    anchor = None
    for match in re.finditer(r"\\usepackage(?:\[[^\]]*\])?\{[^}]*\}[^\n]*\n", main_source):
        if not mask[match.start()] and (begin < 0 or match.start() < begin):
            anchor = match.end()
    if anchor is None:
        doc = re.search(r"\\documentclass(?:\[[^\]]*\])?\{[^}]*\}[^\n]*\n", main_source)
        if doc is None:
            raise FigureError("Could not find the preamble to add \\usepackage{graphicx}.")
        anchor = doc.end()
    return main_source[:anchor] + "\\usepackage{graphicx}\n" + main_source[anchor:]


def section_text_end(tex: str, title: str) -> int:
    """Offset where a section's own text ends (before its first subsection)."""
    sections = split_sections(tex)
    target = next((s for s in sections if s.title == title), None)
    if target is None:
        raise FigureError(f"Section {title!r} not found")
    children = [s.start for s in sections if target.start < s.start < target.end]
    return min(children) if children else target.end


def insert_at_section_end(tex: str, title: str, block: str) -> str:
    end = section_text_end(tex, title)
    head = tex[:end].rstrip()
    tail = tex[end:]
    return f"{head}\n\n{block.strip()}\n\n{tail.lstrip(chr(10))}"


def image_content_block(path: Path) -> dict | None:
    """Claude content block for an image/PDF, downscaled if needed; ``None`` if unusable."""
    suffix = path.suffix.lower()
    data = path.read_bytes()
    if suffix == ".pdf":
        if len(data) > 20_000_000:
            return None
        return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                "data": base64.b64encode(data).decode()}}
    media = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(suffix)
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            too_big = len(data) > VISION_MAX_BYTES or max(image.size) > VISION_MAX_SIDE or media is None
            if too_big:
                image.thumbnail((VISION_MAX_SIDE, VISION_MAX_SIDE))
                buffer = io.BytesIO()
                image.convert("RGB").save(buffer, "JPEG", quality=85)
                data, media = buffer.getvalue(), "image/jpeg"
    except ImportError:
        if media is None or len(data) > VISION_MAX_BYTES:
            return None
    except OSError:
        return None
    return {"type": "image", "source": {"type": "base64", "media_type": media,
                                         "data": base64.b64encode(data).decode()}}

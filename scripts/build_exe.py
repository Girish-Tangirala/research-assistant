"""Build the Windows app and the two zips to hand out.

Run from the project folder with the project's Python:

    .venv\\Scripts\\python scripts\\build_exe.py

Produces in ``dist/``:

* ``ResearchAssistant/`` - the app folder (``ResearchAssistant.exe`` plus its libraries),
* ``ResearchAssistant-windows-<version>.zip`` - that folder zipped, with the user guide; send
  this to colleagues who only want to *use* the app,
* ``ResearchAssistant-source-<version>.zip`` - the source code, README and CLAUDE.md for
  colleagues who want to *change* the app with their own Claude Code.

Nobody's keys or tokens are ever bundled: they live in each user's Windows Credential
Manager, and ``.env`` is left out of both zips.
"""

from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from version import __version__  # noqa: E402

DIST = ROOT / "dist"
BUILD = ROOT / "build"
APP = "ResearchAssistant"
GUIDE = ROOT / "docs" / "USER_GUIDE.md"
# Never shipped in the source zip: local settings/secrets, environments, caches, build output.
SOURCE_EXCLUDE_DIRS = {".venv", "venv", "__pycache__", ".pytest_cache", "build", "dist", ".git", ".claude",
                       ".claude-flow", ".swarm", ".hive-mind"}
SOURCE_EXCLUDE_FILES = {".env"}
SOURCE_SUFFIXES_EXCLUDED = {".pyc", ".pyo", ".log"}
FIRST_STEPS = """Research Assistant - first steps
================================

1. Double-click ResearchAssistant.exe in this folder.
   Windows may say "Windows protected your PC" because the app is not signed:
   click "More info" -> "Run anyway".
2. First start only: the app offers to install Git and MiKTeX for you (a few minutes,
   about 200 MB, no administrator rights). Click "Install now", then "Restart now".
3. Sign in with YOUR OWN Claude API key and Overleaf Git token when the app asks.

The full guide is USER_GUIDE.md in this folder (also Help > User guide in the app).
Keep this whole folder together - the .exe needs the _internal folder next to it.
"""


def make_icon(target: Path) -> Path:
    """A simple app icon (page with text lines and a check mark), drawn with Pillow."""
    from PIL import Image, ImageDraw

    size = 256
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((8, 8, 248, 248), radius=48, fill=(31, 83, 141, 255))
    draw.rounded_rectangle((62, 36, 194, 212), radius=14, fill=(245, 247, 250, 255))
    for i, width in enumerate((96, 110, 80, 104, 66)):
        y = 70 + i * 24
        draw.rounded_rectangle((80, y, 80 + width, y + 9), radius=4, fill=(120, 132, 150, 255))
    draw.ellipse((150, 150, 234, 234), fill=(46, 160, 67, 255))
    draw.line((170, 192, 186, 208, 214, 172), fill=(255, 255, 255, 255), width=12, joint="curve")
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return target


def build_app(icon: Path) -> Path:
    import PyInstaller.__main__

    PyInstaller.__main__.run([
        str(ROOT / "main.py"),
        "--name", APP,
        "--windowed",               # no console window
        "--noconfirm", "--clean",
        "--icon", str(icon),
        "--distpath", str(DIST), "--workpath", str(BUILD / "pyinstaller"), "--specpath", str(BUILD),
        "--paths", str(ROOT),
        "--collect-data", "customtkinter",      # themes and fonts
        "--collect-all", "pypdfium2",           # the PDF renderer and its pdfium.dll
        "--collect-all", "pypdfium2_raw",
        "--hidden-import", "keyring.backends.Windows",
        "--hidden-import", "win32ctypes.core",
        "--add-data", f"{GUIDE}{';' if sys.platform == 'win32' else ':'}docs",
        "--exclude-module", "pytest",
        "--exclude-module", "tests",
    ])
    folder = DIST / APP
    shutil.copy2(GUIDE, folder / GUIDE.name)
    (folder / "READ ME FIRST.txt").write_text(FIRST_STEPS, encoding="utf-8")
    return folder


def zip_folder(folder: Path, target: Path) -> Path:
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(folder.rglob("*")):
            archive.write(path, Path(folder.name) / path.relative_to(folder))
    return target


def zip_source(target: Path) -> Path:
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(ROOT.rglob("*")):
            rel = path.relative_to(ROOT)
            if (any(part in SOURCE_EXCLUDE_DIRS for part in rel.parts) or path.name in SOURCE_EXCLUDE_FILES
                    or path.suffix in SOURCE_SUFFIXES_EXCLUDED or path.is_dir()):
                continue
            if path.stat().st_size == 0 and path.suffix == "":
                continue  # stray empty files left behind by shell hooks
            archive.write(path, Path("ResearchAssistant-source") / rel)
    return target


def main() -> tuple[Path, Path]:
    """Build and zip; returns ``(app zip, source zip)`` (``scripts/release.py`` uploads them)."""
    DIST.mkdir(exist_ok=True)
    icon = make_icon(BUILD / "app.ico")
    folder = build_app(icon)
    app_zip = zip_folder(folder, DIST / f"{APP}-windows-{__version__}.zip")
    source_zip = zip_source(DIST / f"{APP}-source-{__version__}.zip")
    for item in (folder / f"{APP}.exe", app_zip, source_zip):
        size = item.stat().st_size / 1e6
        print(f"  {item.relative_to(ROOT)}  ({size:.1f} MB)")
    return app_zip, source_zip


if __name__ == "__main__":
    main()

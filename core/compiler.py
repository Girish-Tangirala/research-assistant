"""LaTeX compilation with structured error reporting.

Uses ``latexmk`` when available (it needs Perl; handles BibTeX/Biber and rerun
cycles) and otherwise runs ``engine → bibtex|biber → engine ×2`` directly. The
engine (pdflatex / xelatex / lualatex) and bibliography tool are detected from
the document, mirroring Overleaf's compiler setting as closely as a repository
allows (``% !TEX program = xelatex`` magic comments are honoured). Shell escape is
always disabled because compiled sources may contain LLM-generated text.
SyncTeX data is written next to the PDF so the preview can map clicks to source lines.
Build output goes to a directory outside the repository so no artefacts are
ever committed.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from config import LatexSettings
from core.latex_parser import flatten_inputs, strip_comments
from core.proc import NO_WINDOW

_ERROR_LINE_RE = re.compile(r"^(?:!.*|.*:\d+: .*)$", re.MULTILINE)
_UNDEF_RE = re.compile(r"(?:Citation|Reference) `([^']+)' on page \d+ undefined", re.MULTILINE)


_MAGIC_PROGRAM_RE = re.compile(r"^%\s*!\s*TEX\s+(?:TS-)?program\s*=\s*(\w+)", re.I | re.M)
_LUA_RE = re.compile(r"\\(?:directlua|luaexec)\b|\\usepackage(?:\[[^\]]*\])?\{[^}]*\b(?:luacode|luatexbase)\b")
_XE_RE = re.compile(r"\\usepackage(?:\[[^\]]*\])?\{[^}]*\b(?:fontspec|unicode-math|polyglossia|xeCJK)\b")
_BIBLATEX_RE = re.compile(r"\\usepackage(\[[^\]]*\])?\{biblatex\}")
_BIBTEX_RE = re.compile(r"\\bibliography\s*\{")
LATEXMK_ENGINE_FLAGS = {"pdflatex": "-pdf", "xelatex": "-pdfxe", "lualatex": "-pdflua"}


def detect_engine(tex: str) -> str:
    """Pick pdflatex / xelatex / lualatex for a document."""
    magic = _MAGIC_PROGRAM_RE.search(tex)
    if magic and magic.group(1).lower() in LATEXMK_ENGINE_FLAGS:
        return magic.group(1).lower()
    body = strip_comments(tex)
    if _LUA_RE.search(body):
        return "lualatex"
    if _XE_RE.search(body):
        return "xelatex"
    return "pdflatex"


def detect_bib_tool(tex: str) -> str | None:
    """``biber``, ``bibtex`` or ``None`` depending on how the bibliography is built."""
    body = strip_comments(tex)
    biblatex = _BIBLATEX_RE.search(body)
    if biblatex:
        return "bibtex" if re.search(r"backend\s*=\s*bibtex", biblatex.group(1) or "") else "biber"
    if _BIBTEX_RE.search(body):
        return "bibtex"
    return None


class CompilerNotFoundError(RuntimeError):
    """No LaTeX toolchain is installed / configured."""


@dataclass
class CompileResult:
    success: bool
    pdf_path: Path | None
    returncode: int
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    log_tail: str = ""

    @property
    def clean(self) -> bool:
        """A PDF was produced and LaTeX reported no errors."""
        return self.success and not self.errors

    def summary(self) -> str:
        extra = f" ({len(self.warnings)} undefined refs/cites)" if self.warnings else ""
        if self.clean:
            return f"Compiled successfully -> {self.pdf_path}{extra}"
        errors = "\n".join(self.errors[:15]) or self.log_tail[-1500:]
        if self.success:
            return (f"Compiled with {len(self.errors)} LaTeX error(s) - LaTeX recovered and still produced "
                    f"the PDF, as Overleaf does -> {self.pdf_path}{extra}:\n{errors}")
        return f"Compilation failed (exit {self.returncode}), no PDF was produced:\n{errors}"


class LatexCompiler:
    """Compile a LaTeX project into a PDF."""

    def __init__(self, settings: LatexSettings, build_root: Path) -> None:
        self.settings = settings
        self.build_root = build_root

    @property
    def available(self) -> bool:
        return bool(self.settings.latexmk_path or self.settings.pdflatex_path)

    def _tool(self, name: str) -> str | None:
        """Locate a TeX binary next to pdflatex first (same distribution), then on PATH."""
        if name == "pdflatex":
            return self.settings.pdflatex_path
        if self.settings.pdflatex_path:
            base = Path(self.settings.pdflatex_path)
            sibling = base.with_name(name + base.suffix)
            if sibling.exists():
                return str(sibling)
        return shutil.which(name)

    def compile(self, main_tex: Path, project_root: Path) -> CompileResult:
        """Compile ``main_tex``.

        Raises:
            CompilerNotFoundError: if neither latexmk nor pdflatex is available.
        """
        outdir = self.build_root / project_root.name
        outdir.mkdir(parents=True, exist_ok=True)
        source = flatten_inputs(main_tex, project_root)
        engine = detect_engine(source)
        bib_tool = detect_bib_tool(source)
        if self.settings.latexmk_path and self.settings.compiler == "latexmk":
            steps = [[
                # -f: keep going after errors and keep the PDF, as Overleaf (which runs latexmk -f) does;
                # -g: always rebuild (latexmk otherwise skips a run whose previous attempt had errors).
                self.settings.latexmk_path, LATEXMK_ENGINE_FLAGS[engine], "-f", "-g", "-interaction=nonstopmode",
                "-file-line-error", "-no-shell-escape", "-synctex=1", f"-outdir={outdir}",
                main_tex.name,
            ]]
        elif self.settings.pdflatex_path:
            engine_path = self._tool(engine)
            if engine_path is None:
                raise CompilerNotFoundError(f"This paper needs {engine}, which was not found.")
            run = [engine_path, "-interaction=nonstopmode", "-file-line-error",
                   "-no-shell-escape", "-synctex=1", f"-output-directory={outdir}", main_tex.name]
            steps = [run]
            if bib_tool == "biber" and self._tool("biber"):
                steps.append([self._tool("biber"), f"--output-directory={outdir}", main_tex.stem])
            elif bib_tool == "bibtex" and self.settings.bibtex_path:
                steps.append([self.settings.bibtex_path, str(outdir / main_tex.stem)])
            steps += [run, run]
        else:
            raise CompilerNotFoundError("No LaTeX compiler was found (install MiKTeX or TeX Live, "
                                        "or set PDFLATEX_PATH).")

        env = os.environ.copy()
        # The TeX tools may have been found outside the inherited PATH; latexmk and
        # the engines call each other (and bibtex/biber) by name, so expose their folder.
        tex_bin = Path(self.settings.pdflatex_path or self.settings.latexmk_path).parent
        env["PATH"] = os.pathsep.join([str(tex_bin), env.get("PATH", "")])
        # Let bibtex (run against outdir) find .bib/.bst files in the project.
        for var in ("BIBINPUTS", "BSTINPUTS", "TEXINPUTS"):
            env[var] = os.pathsep.join([str(main_tex.parent), str(project_root), env.get(var, "")])

        pdf = outdir / f"{main_tex.stem}.pdf"
        # An earlier build's PDF must not count as output. Remove it (MiKTeX can keep the old
        # timestamp when it rewrites the file); if another program holds it open, compare timestamps.
        stale = None
        try:
            pdf.unlink(missing_ok=True)
        except OSError:
            stale = pdf.stat().st_mtime_ns

        def fresh_pdf() -> bool:
            return pdf.exists() and pdf.stat().st_mtime_ns != stale

        returncode = 0
        output = ""
        for cmd in steps:
            try:
                proc = subprocess.run(
                    cmd, cwd=main_tex.parent, env=env, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=self.settings.timeout_s,
                    stdin=subprocess.DEVNULL, creationflags=NO_WINDOW,
                )
            except FileNotFoundError as exc:
                raise CompilerNotFoundError(f"Compiler executable not found: {cmd[0]}") from exc
            except subprocess.TimeoutExpired:
                return CompileResult(False, None, -1, [f"Timed out after {self.settings.timeout_s}s: {Path(cmd[0]).name}"])
            output += proc.stdout + proc.stderr
            returncode = proc.returncode
            is_bib_step = Path(cmd[0]).stem.lower() in {"bibtex", "biber"}
            # Like Overleaf, keep going after recoverable errors; stop only when no PDF came out.
            # (Bibliography tools also return non-zero for mere warnings.)
            if returncode != 0 and not is_bib_step and not fresh_pdf():
                break

        log_file = outdir / f"{main_tex.stem}.log"
        log_text = log_file.read_text(encoding="utf-8", errors="replace") if log_file.exists() else output
        errors = extract_errors(log_text)
        warnings = sorted(set(_UNDEF_RE.findall(log_text)))
        produced = fresh_pdf()
        return CompileResult(
            success=produced,
            pdf_path=pdf if produced else None,
            returncode=returncode,
            errors=errors if (errors or produced) else [f"LaTeX stopped without producing a PDF (exit {returncode})."],
            warnings=[f"undefined: {w}" for w in warnings],
            log_tail=log_text[-4000:],
        )


def _error_key(entry: str) -> str:
    """An error without its file/line position, so edits elsewhere don't make old errors look new."""
    message = re.sub(r"^.*?:\d+: ", "", entry)
    return re.sub(r"\s+l\.\d+.*$", "", message).strip()


def new_errors(before: list[str], after: list[str]) -> list[str]:
    """Errors in ``after`` that ``before`` did not have (compared by message, counting repeats)."""
    remaining = Counter(_error_key(e) for e in before)
    added = []
    for entry in after:
        key = _error_key(entry)
        if remaining[key]:
            remaining[key] -= 1
        else:
            added.append(entry)
    return added


def extract_errors(log_text: str) -> list[str]:
    """Pull ``! ...`` and ``file:line: ...`` error lines (with one line of context)."""
    lines = log_text.splitlines()
    errors: list[str] = []
    for idx, line in enumerate(lines):
        if _ERROR_LINE_RE.fullmatch(line):
            context = lines[idx + 1].strip() if idx + 1 < len(lines) else ""
            entry = f"{line.strip()} {context}".strip()
            if entry not in errors:
                errors.append(entry)
    return errors

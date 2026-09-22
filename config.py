"""Central (non-secret) configuration for the Scientific Research Assistant Agent.

Secrets are **not** configured here: the Claude API key, Git tokens and the
optional OpenAlex key are entered in the app and persisted in the operating
system's credential vault (see :mod:`core.credentials`).

Optional environment variables (or a ``.env`` file next to this module)
-----------------------------------------------------------------------
AGENT_MODEL                Claude model id (default ``claude-opus-5``).
AGENT_EFFORT               low | medium | high | xhigh | max (default ``high``).
AGENT_MAX_TOKENS           Max output tokens per LLM turn (default 32000).
AGENT_MAX_STEPS            Max ReAct iterations (default 40).
AGENT_SERVER_FALLBACKS     ``true`` to enable server-side refusal fallbacks.
AGENT_WORKSPACE            Directory for clones, build output, reports, settings.
GIT_PUSH_STRATEGY          ``auto`` | ``feature-branch`` | ``merge-to-default``.
LATEX_COMPILER             ``latexmk`` (default) or ``pdflatex``.
LATEXMK_PATH / PDFLATEX_PATH / BIBTEX_PATH   Explicit executable paths.
LATEX_TIMEOUT              Compile timeout in seconds (default 600).
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

try:  # python-dotenv is optional at import time (tests run without it).
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).with_name(".env"))
except ImportError:  # pragma: no cover
    pass

VALID_EFFORTS = ("low", "medium", "high", "xhigh", "max")
VALID_PUSH_STRATEGIES = ("auto", "feature-branch", "merge-to-default")


def _env_str(name: str, default: str) -> str:
    value = os.getenv(name, "").strip()
    return value or default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be an integer, got {raw!r}") from exc


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _registry_path() -> str:
    """Current user + machine PATH from the Windows registry.

    A process inherits PATH when it starts, so programs installed afterwards
    (e.g. MiKTeX adding itself to PATH) are invisible until everything is
    restarted. Reading the registry avoids that.
    """
    if sys.platform != "win32":
        return ""
    import winreg

    parts = []
    for hive, key in ((winreg.HKEY_CURRENT_USER, "Environment"),
                      (winreg.HKEY_LOCAL_MACHINE,
                       r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")):
        try:
            with winreg.OpenKey(hive, key) as handle:
                value, _ = winreg.QueryValueEx(handle, "Path")
                parts.append(os.path.expandvars(value))
        except OSError:
            continue
    return os.pathsep.join(parts)


def _tex_install_dirs() -> list[str]:
    """Default MiKTeX / TeX Live binary folders (newest TeX Live first)."""
    if sys.platform != "win32":
        return ["/Library/TeX/texbin", "/usr/local/bin", "/usr/bin"]
    local = os.getenv("LOCALAPPDATA", "")
    program_files = [os.getenv("ProgramFiles", r"C:\Program Files"), os.getenv("ProgramFiles(x86)", "")]
    dirs = [os.path.join(local, "Programs", "MiKTeX", "miktex", "bin", "x64")]
    dirs += [os.path.join(pf, "MiKTeX", "miktex", "bin", "x64") for pf in program_files if pf]
    texlive = sorted(Path("C:/texlive").glob("20*/bin/*"), reverse=True) if Path("C:/texlive").is_dir() else []
    return dirs + [str(d) for d in texlive]


def _which(explicit_env: str, executable: str) -> str | None:
    """Find an executable: explicit env var, then PATH (inherited, then current registry value),
    then the default TeX install folders."""
    explicit = os.getenv(explicit_env, "").strip()
    if explicit:
        return explicit
    for search_path in (None, _registry_path(), os.pathsep.join(_tex_install_dirs())):
        if search_path == "":
            continue
        found = shutil.which(executable, path=search_path)
        if found:
            return found
    return None


@dataclass(frozen=True)
class LLMSettings:
    """Claude API settings."""

    model: str = "claude-opus-5"
    effort: str = "high"
    max_tokens: int = 32000
    max_agent_steps: int = 40
    use_server_fallbacks: bool = True


@dataclass(frozen=True)
class GitSettings:
    """Git synchronisation settings (identity comes from the in-app Git login)."""

    author_name: str = "Research Assistant Agent"
    author_email: str = "agent@localhost"
    push_strategy: str = "auto"
    feature_branch_prefix: str = "agent/"
    remote_name: str = "origin"


@dataclass(frozen=True)
class LatexSettings:
    """LaTeX toolchain settings."""

    compiler: str = "latexmk"
    latexmk_path: str | None = None
    pdflatex_path: str | None = None
    bibtex_path: str | None = None
    timeout_s: int = 600


@dataclass(frozen=True)
class AppConfig:
    """Top-level immutable application configuration."""

    llm: LLMSettings
    git: GitSettings
    latex: LatexSettings
    workspace: Path

    @property
    def build_dir(self) -> Path:
        """Directory for LaTeX build output (kept outside the repositories)."""
        return self.workspace / "_build"

    @property
    def reports_dir(self) -> Path:
        """Directory for generated Markdown reports and .bib exports."""
        return self.workspace / "reports"

    @property
    def papers_dir(self) -> Path:
        """Default parent directory for cloned papers."""
        return self.workspace / "papers"

    @property
    def settings_file(self) -> Path:
        """JSON file with the paper list and UI preferences (no secrets)."""
        return self.workspace / "app_state.json"

    @classmethod
    def from_env(cls) -> "AppConfig":
        """Build the configuration from the current environment."""
        workspace = Path(
            _env_str("AGENT_WORKSPACE", str(Path.home() / ".research_agent"))
        ).expanduser()
        llm = LLMSettings(
            model=_env_str("AGENT_MODEL", "claude-opus-5"),
            effort=_env_str("AGENT_EFFORT", "high").lower(),
            max_tokens=_env_int("AGENT_MAX_TOKENS", 32000),
            max_agent_steps=_env_int("AGENT_MAX_STEPS", 40),
            use_server_fallbacks=_env_bool("AGENT_SERVER_FALLBACKS", True),
        )
        git = GitSettings(push_strategy=_env_str("GIT_PUSH_STRATEGY", "auto").lower())
        latex = LatexSettings(
            compiler=_env_str("LATEX_COMPILER", "latexmk").lower(),
            # latexmk is a Perl script (MiKTeX ships only a wrapper), so require Perl.
            latexmk_path=_which("LATEXMK_PATH", "latexmk") if (
                os.getenv("LATEXMK_PATH") or _which("PERL_PATH", "perl")) else None,
            pdflatex_path=_which("PDFLATEX_PATH", "pdflatex"),
            bibtex_path=_which("BIBTEX_PATH", "bibtex"),
            timeout_s=_env_int("LATEX_TIMEOUT", 600),
        )
        config = cls(llm=llm, git=git, latex=latex, workspace=workspace)
        for directory in (config.workspace, config.build_dir, config.reports_dir, config.papers_dir):
            directory.mkdir(parents=True, exist_ok=True)
        return config

    def validate(self) -> list[str]:
        """Return human-readable configuration problems (empty list = OK)."""
        problems: list[str] = []
        if self.llm.effort not in VALID_EFFORTS:
            problems.append(f"AGENT_EFFORT must be one of {VALID_EFFORTS}, got {self.llm.effort!r}")
        if self.llm.max_tokens < 1024:
            problems.append("AGENT_MAX_TOKENS should be at least 1024")
        if self.git.push_strategy not in VALID_PUSH_STRATEGIES:
            problems.append(
                f"GIT_PUSH_STRATEGY must be one of {VALID_PUSH_STRATEGIES}, "
                f"got {self.git.push_strategy!r}"
            )
        if self.latex.compiler not in ("latexmk", "pdflatex"):
            problems.append("LATEX_COMPILER must be 'latexmk' or 'pdflatex'")
        if not (self.latex.latexmk_path or self.latex.pdflatex_path):
            problems.append(
                "No LaTeX compiler found (latexmk/pdflatex) on PATH or in the usual MiKTeX / TeX Live "
                "folders. Install MiKTeX or set PDFLATEX_PATH in .env - compilation checks will be skipped."
            )
        return problems

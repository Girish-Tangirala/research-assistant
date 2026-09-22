"""Corruption-proof LaTeX editing.

Strategy
--------
1. **Protect** – every fragile construct (verbatim, comments, math, floats,
   section headers, ``\\cite``/``\\ref``/``\\label``..., environment markers) is
   swapped for an opaque placeholder token such as ``⟦L0007⟧`` before the text
   is shown to the LLM. The model only ever sees and edits prose.
2. **Restore** – the model's output must contain every placeholder exactly once,
   no invented placeholders, and structural markers in their original order.
3. **Validate** – the restored LaTeX is checked for balanced braces, properly
   nested environments, unchanged math, unchanged citation/label/ref sets, no
   new unescaped special characters, and no dangerous primitives.

Any failure raises :class:`LatexIntegrityError` with a list of problems that
can be fed back to the model for a repair attempt.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

from core.latex_parser import CITE_RE, comment_mask, match_brace

TOKEN_RE = re.compile(r"⟦L(\d{4})⟧")

VERBATIM_ENVS = ("verbatim", "Verbatim", "lstlisting", "minted", "comment", "alltt")
MATH_ENVS = (
    "equation", "align", "alignat", "flalign", "gather", "multline",
    "eqnarray", "math", "displaymath", "split", "cases",
)
OPAQUE_ENVS = (
    "figure", "table", "tabular", "tabularx", "longtable", "algorithm",
    "algorithmic", "tikzpicture", "subfigure", "wrapfigure",
)
REF_COMMANDS = (
    "ref", "eqref", "autoref", "cref", "Cref", "pageref", "label", "url",
    "input", "include", "includegraphics", "bibliography", "bibliographystyle",
    "addbibresource", "nameref", "hyperref",
)
HEADER_COMMANDS = ("part", "chapter", "section", "subsection", "subsubsection", "paragraph")
FORBIDDEN_PRIMITIVES = (
    r"\write18", r"\immediate", r"\openout", r"\directlua", r"\catcode",
    r"\input", r"\include", r"\documentclass", r"\usepackage",
    r"\begin{document}", r"\end{document}", r"\ShellEscape",
)
PROSE_SPECIALS = ("&", "#", "_", "^")


class LatexIntegrityError(ValueError):
    """Raised when an edit would corrupt the LaTeX source."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("LaTeX integrity check failed:\n- " + "\n- ".join(problems))


# ---------------------------------------------------------------------- #
# Protection
# ---------------------------------------------------------------------- #
@dataclass
class ProtectedText:
    """Result of :func:`protect`."""

    text: str
    originals: dict[str, str] = field(default_factory=dict)
    structural: list[str] = field(default_factory=list)  # order-sensitive tokens
    comment_tokens: set[str] = field(default_factory=set)

    @property
    def tokens(self) -> list[str]:
        """Top-level placeholder tokens in document order."""
        return [m.group(0) for m in TOKEN_RE.finditer(self.text)]


class _Protector:
    def __init__(self) -> None:
        self.originals: dict[str, str] = {}
        self.structural_ids: set[str] = set()
        self.comment_ids: set[str] = set()

    def token(self, original: str, structural: bool = False, comment: bool = False) -> str:
        tok = f"⟦L{len(self.originals):04d}⟧"
        self.originals[tok] = original
        if structural:
            self.structural_ids.add(tok)
        if comment:
            self.comment_ids.add(tok)
        return tok

    def sub(self, pattern: re.Pattern[str], text: str, structural: bool = False) -> str:
        return pattern.sub(lambda m: self.token(m.group(0), structural), text)

    def comments(self, text: str) -> str:
        mask = comment_mask(text)
        out: list[str] = []
        i = 0
        while i < len(text):
            if mask[i]:
                j = i
                while j < len(text) and mask[j]:
                    j += 1
                out.append(self.token(text[i:j], comment=True))
                i = j
            else:
                out.append(text[i])
                i += 1
        return "".join(out)

    def commands(self, text: str, names: tuple[str, ...], n_args: int, structural: bool) -> str:
        """Protect ``\\name*[opt]{arg}...`` with balanced-brace arguments."""
        pattern = re.compile(r"\\(?:" + "|".join(names) + r")\*?(?![a-zA-Z])")
        out: list[str] = []
        pos = 0
        for match in pattern.finditer(text):
            if match.start() < pos:
                continue
            end = match.end()
            try:
                while True:
                    opt = re.compile(r"\s*\[[^\]]*\]").match(text, end)
                    if not opt:
                        break
                    end = opt.end()
                for _ in range(n_args):
                    brace = re.compile(r"\s*\{").match(text, end)
                    if not brace:
                        break
                    end = match_brace(text, brace.end() - 1) + 1
            except ValueError:
                continue
            out.append(text[pos : match.start()])
            out.append(self.token(text[match.start() : end], structural))
            pos = end
        out.append(text[pos:])
        return "".join(out)


def _env_pattern(names: tuple[str, ...]) -> re.Pattern[str]:
    alternation = "|".join(re.escape(n) for n in names)
    return re.compile(
        r"\\begin\{(?P<env>(?:" + alternation + r")\*?)\}.*?\\end\{(?P=env)\}", re.DOTALL
    )


_VERBATIM_RE = _env_pattern(VERBATIM_ENVS)
_MATH_ENV_RE = _env_pattern(MATH_ENVS)
_OPAQUE_ENV_RE = _env_pattern(OPAQUE_ENVS)
_DISPLAY_MATH_RE = re.compile(r"\\\[.*?\\\]|(?<!\\)\$\$.*?(?<!\\)\$\$|\\\(.*?\\\)", re.DOTALL)
_INLINE_MATH_RE = re.compile(r"(?<!\\)\$(?:\\.|[^$\\])+?\$", re.DOTALL)
_ENV_MARKER_RE = re.compile(r"\\begin\{[^}]+\}(?:\[[^\]]*\])?|\\end\{[^}]+\}")


def protect(tex: str) -> ProtectedText:
    """Replace fragile LaTeX constructs by placeholder tokens."""
    p = _Protector()
    text = p.sub(_VERBATIM_RE, tex)
    text = p.comments(text)
    text = p.sub(_MATH_ENV_RE, text)
    text = p.sub(_OPAQUE_ENV_RE, text)
    text = p.sub(_DISPLAY_MATH_RE, text)
    text = p.sub(_INLINE_MATH_RE, text)
    text = p.commands(text, HEADER_COMMANDS, n_args=1, structural=True)
    text = p.sub(CITE_RE, text)
    text = p.commands(text, REF_COMMANDS, n_args=1, structural=False)
    text = p.commands(text, ("href",), n_args=1, structural=False)
    text = p.sub(_ENV_MARKER_RE, text, structural=True)
    top_level = [m.group(0) for m in TOKEN_RE.finditer(text)]
    return ProtectedText(
        text=text,
        originals=p.originals,
        structural=[t for t in top_level if t in p.structural_ids],
        comment_tokens={t for t in top_level if t in p.comment_ids},
    )


def expand_tokens(text: str, originals: dict[str, str], max_depth: int = 10) -> str:
    """Replace tokens (recursively, for nested protection) by their originals."""
    for _ in range(max_depth):
        if not TOKEN_RE.search(text):
            return text
        text = TOKEN_RE.sub(lambda m: originals.get(m.group(0), m.group(0)), text)
    return text


def restore(protected: ProtectedText, edited: str) -> str:
    """Validate placeholder usage in ``edited`` and expand it back to LaTeX.

    Raises:
        LatexIntegrityError: on missing, duplicated, invented or reordered tokens.
    """
    expected = protected.tokens
    found = [m.group(0) for m in TOKEN_RE.finditer(edited)]
    problems: list[str] = []
    counts = Counter(found)
    missing = [t for t in expected if t not in counts]
    if missing:
        problems.append(
            "Missing placeholders (must be kept verbatim): "
            + ", ".join(f"{t} = {protected.originals[t][:60]!r}" for t in missing)
        )
    dupes = [t for t, c in counts.items() if c > 1]
    if dupes:
        problems.append(f"Duplicated placeholders: {', '.join(dupes)}")
    unknown = [t for t in counts if t not in protected.originals or t not in expected]
    if unknown:
        problems.append(f"Unknown placeholders introduced: {', '.join(unknown)}")
    order = [t for t in found if t in protected.structural]
    if not problems and order != protected.structural:
        problems.append("Structural placeholders (section headers / environment markers) were reordered.")
    if problems:
        raise LatexIntegrityError(problems)
    return expand_tokens(edited, protected.originals)


# ---------------------------------------------------------------------- #
# Validation
# ---------------------------------------------------------------------- #
def _without_comments(tex: str) -> str:
    mask = comment_mask(tex)
    return "".join(" " if m else ch for ch, m in zip(tex, mask))


def check_braces(tex: str) -> list[str]:
    """Report unbalanced ``{``/``}`` (escaped braces and comments ignored)."""
    text = _without_comments(tex)
    depth = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                return [f"Unmatched '}}' near: {text[max(0, i - 40) : i + 1]!r}"]
        i += 1
    return [f"{depth} unclosed '{{' brace(s)"] if depth else []


def check_environments(tex: str) -> list[str]:
    """Report improperly nested ``\\begin``/``\\end`` pairs."""
    stack: list[str] = []
    text = _without_comments(tex)
    text = _VERBATIM_RE.sub("", text)
    for match in re.finditer(r"\\(begin|end)\{([^}]+)\}", text):
        kind, env = match.groups()
        if kind == "begin":
            stack.append(env)
        elif not stack:
            return [f"\\end{{{env}}} without matching \\begin"]
        elif stack[-1] != env:
            return [f"\\end{{{env}}} closes \\begin{{{stack[-1]}}}"]
        else:
            stack.pop()
    return [f"Unclosed environment(s): {', '.join(stack)}"] if stack else []


def check_inline_math(tex: str) -> list[str]:
    text = _VERBATIM_RE.sub("", _without_comments(tex))
    dollars = len(re.findall(r"(?<!\\)\$", text))
    return ["Odd number of unescaped '$' – inline math is unbalanced"] if dollars % 2 else []


def math_segments(tex: str) -> Counter[str]:
    """Multiset of math blocks, whitespace-normalised."""
    text = _without_comments(tex)
    segments = [m.group(0) for m in _MATH_ENV_RE.finditer(text)]
    text = _MATH_ENV_RE.sub(" ", text)
    segments += [m.group(0) for m in _DISPLAY_MATH_RE.finditer(text)]
    text = _DISPLAY_MATH_RE.sub(" ", text)
    segments += [m.group(0) for m in _INLINE_MATH_RE.finditer(text)]
    return Counter(" ".join(s.split()) for s in segments)


def _keys(pattern: str, tex: str) -> Counter[str]:
    text = _without_comments(tex)
    keys: Counter[str] = Counter()
    for m in re.finditer(pattern, text):
        for k in m.group(1).split(","):
            if k.strip():
                keys[k.strip()] += 1
    return keys


def cite_keys(tex: str) -> set[str]:
    text = _without_comments(tex)
    return {k.strip() for m in CITE_RE.finditer(text) for k in m.group("keys").split(",") if k.strip()}


def forbidden_primitives(tex: str) -> set[str]:
    text = _without_comments(tex)
    return {p for p in FORBIDDEN_PRIMITIVES if re.search(re.escape(p) + r"(?![a-zA-Z])", text)}


def prose_special_counts(protected_text: str) -> Counter[str]:
    """Count unescaped special characters outside protected tokens."""
    text = TOKEN_RE.sub(" ", protected_text)
    return Counter(
        {ch: len(re.findall(r"(?<!\\)" + re.escape(ch), text)) for ch in PROSE_SPECIALS}
    )


@dataclass
class IntegrityReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def raise_if_failed(self) -> None:
        if self.errors:
            raise LatexIntegrityError(self.errors)


def validate_edit(original: str, edited: str, allowed_new_cites: frozenset[str] = frozenset()) -> IntegrityReport:
    """Check that ``edited`` changed prose only, relative to ``original``."""
    report = IntegrityReport()
    report.errors += check_braces(edited) + check_environments(edited) + check_inline_math(edited)
    if math_segments(original) != math_segments(edited):
        report.errors.append("Math content was modified, added or removed.")
    before, after = cite_keys(original), cite_keys(edited)
    if before - after:
        report.errors.append(f"Citations removed: {sorted(before - after)}")
    if after - before - allowed_new_cites:
        report.errors.append(f"Unexpected new citation keys: {sorted(after - before - allowed_new_cites)}")
    for name, pattern in (("labels", r"\\label\{([^}]*)\}"), ("references", r"\\(?:[cC]?ref|eqref|autoref|pageref)\{([^}]*)\}")):
        if set(_keys(pattern, original)) != set(_keys(pattern, edited)):
            report.errors.append(f"Set of {name} changed.")
    envs_before = Counter(re.findall(r"\\begin\{([^}]+)\}", _without_comments(original)))
    envs_after = Counter(re.findall(r"\\begin\{([^}]+)\}", _without_comments(edited)))
    if envs_before != envs_after:
        report.errors.append(f"Environments changed: before={dict(envs_before)} after={dict(envs_after)}")
    new_forbidden = forbidden_primitives(edited) - forbidden_primitives(original)
    if new_forbidden:
        report.errors.append(f"Forbidden primitives introduced: {sorted(new_forbidden)}")
    p_before, p_after = protect(original), protect(edited)
    if len(p_after.comment_tokens) > len(p_before.comment_tokens):
        report.errors.append("New '%' comment introduced – escape literal percent signs as \\%.")
    for ch, count in prose_special_counts(p_after.text).items():
        if count > prose_special_counts(p_before.text)[ch]:
            report.errors.append(f"New unescaped '{ch}' in prose – write \\{ch} instead.")
    cmds_before = Counter(re.findall(r"\\[a-zA-Z]+", p_before.text))
    cmds_after = Counter(re.findall(r"\\[a-zA-Z]+", p_after.text))
    if cmds_before != cmds_after:
        report.warnings.append(
            f"Inline formatting commands changed: removed={dict(cmds_before - cmds_after)} "
            f"added={dict(cmds_after - cmds_before)}"
        )
    return report


def validate_fragment(tex: str, allowed_cites: set[str], forbid_headers: bool = True) -> IntegrityReport:
    """Validate newly generated LaTeX (e.g. a synthesized Related Work body)."""
    report = IntegrityReport()
    report.errors += check_braces(tex) + check_environments(tex) + check_inline_math(tex)
    unknown = cite_keys(tex) - allowed_cites
    if unknown:
        report.errors.append(f"Citation keys not present in the bibliography: {sorted(unknown)}")
    if forbidden_primitives(tex):
        report.errors.append(f"Forbidden primitives: {sorted(forbidden_primitives(tex))}")
    if forbid_headers and re.search(r"\\(?:part|chapter|section)\*?\s*[\[{]", _without_comments(tex)):
        report.errors.append("Fragment must not contain \\section/\\chapter headers (body only).")
    if protect(tex).comment_tokens:
        report.warnings.append("Fragment contains '%' comments; make sure literal percents are escaped.")
    for ch, count in prose_special_counts(protect(tex).text).items():
        if count:
            report.errors.append(f"Unescaped '{ch}' in prose – write \\{ch} instead.")
    if not cite_keys(tex):
        report.warnings.append("Fragment contains no citations.")
    return report


def safe_rewrite(tex: str, rewrite: Callable[[str], str]) -> tuple[str, IntegrityReport]:
    """Protect → rewrite prose via ``rewrite`` → restore → validate.

    Raises:
        LatexIntegrityError: if placeholders or the resulting LaTeX are invalid.
    """
    protected = protect(tex)
    edited = restore(protected, rewrite(protected.text))
    report = validate_edit(tex, edited)
    report.raise_if_failed()
    return edited, report

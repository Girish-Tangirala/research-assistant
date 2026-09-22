import re

import pytest

from core.latex_parser import find_section
from core.latex_safety import (
    LatexIntegrityError, TOKEN_RE, protect, restore, safe_rewrite, validate_edit, validate_fragment,
)
from tests.conftest import MAIN_TEX

INTRO = find_section(MAIN_TEX, "Introduction").body(MAIN_TEX)


def test_protect_hides_fragile_constructs():
    p = protect(INTRO)
    for fragile in ("$", "\\cite", "\\citep", "\\label", "\\eqref", "\\begin", "\\end", "\\subsection", "%"):
        assert fragile not in TOKEN_RE.sub("", p.text).replace("\\%", ""), fragile
    assert "Protein folding is hard" in p.text
    assert restore(p, p.text) == INTRO


def test_identity_rewrite_roundtrip():
    edited, report = safe_rewrite(INTRO, lambda text: text)
    assert edited == INTRO and report.ok


def test_prose_rewrite_is_accepted():
    edited, _ = safe_rewrite(INTRO, lambda t: t.replace("Protein folding is hard", "Predicting protein structure is difficult"))
    assert "Predicting protein structure is difficult" in edited
    assert "\\frac{1}{N}" in edited


def test_missing_placeholder_rejected():
    p = protect(INTRO)
    first = TOKEN_RE.search(p.text).group(0)
    with pytest.raises(LatexIntegrityError, match="Missing placeholders"):
        restore(p, p.text.replace(first, "", 1))


def test_invented_and_duplicated_placeholders_rejected():
    p = protect(INTRO)
    first = TOKEN_RE.search(p.text).group(0)
    with pytest.raises(LatexIntegrityError) as exc:
        restore(p, p.text + f" {first} ⟦L9999⟧")
    assert any("Duplicated" in m for m in exc.value.problems)
    assert any("Unknown" in m for m in exc.value.problems)


def test_reordered_structure_rejected():
    p = protect(INTRO)
    structural = p.structural
    assert len(structural) >= 3
    a, b = structural[1], structural[2]
    swapped = p.text.replace(a, "@@A@@").replace(b, a).replace("@@A@@", b)
    with pytest.raises(LatexIntegrityError, match="reordered"):
        restore(p, swapped)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (lambda t: t.replace("\\sum_i \\ell_i", "\\sum_j \\ell_j"), "Math content"),
        (lambda t: t.replace("\\cite{jumper2021}", ""), "Citations removed"),
        (lambda t: t.replace("\\cite{jumper2021}", "\\cite{jumper2021,fake2020}"), "Unexpected new citation"),
        (lambda t: t.replace("50\\% faster", "50% faster"), "comment"),
        (lambda t: t.replace("is hard", "is hard & slow"), "unescaped '&'"),
        (lambda t: t.replace("\\end{itemize}", ""), "nvironment"),
        (lambda t: t.replace("Experiments on CASP.", "Experiments {on CASP."), "brace"),
        (lambda t: t + "\n\\immediate\\write18{rm -rf /}", "Forbidden"),
    ],
)
def test_validate_edit_catches_corruption(mutation, expected):
    report = validate_edit(INTRO, mutation(INTRO))
    assert not report.ok
    assert any(re.search(expected, e) for e in report.errors), report.errors


def test_validate_fragment():
    ok = validate_fragment("Prior work~\\cite{kipf2017} uses graphs.", {"kipf2017"})
    assert ok.ok
    bad = validate_fragment("\\section{X} R&D \\cite{nope}", {"kipf2017"})
    joined = " ".join(bad.errors)
    assert "nope" in joined and "\\section" in joined and "'&'" in joined

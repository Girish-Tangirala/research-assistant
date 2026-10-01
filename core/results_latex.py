"""Turning a :class:`~core.results_data.ResultTable` into LaTeX.

Charts become ``pgfplots`` code and tables ``booktabs`` code, so the numbers are
real text in the ``.tex`` file: they show up in the approval diff, can be edited
by hand in Overleaf afterwards, and use the paper's own fonts. Nothing here calls
an LLM - a :class:`ChartSpec` (which the model may choose) plus a table (which
the model never touches) fully determine the output.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from core.results_data import ResultTable, ResultsError

KINDS = ("line", "bar", "matrix", "table")
MAX_SERIES = 8
MAX_BAR_GROUPS = 24
MAX_MATRIX_CLASSES = 30
DEFAULT_WIDTH = r"0.85\linewidth"
# A white-to-blue ramp defined inline, so no pgfplots colormap library is needed. It stops
# well short of black on purpose: the count is printed in black inside every cell.
MATRIX_COLORMAP = "colormap={conf}{color=(white) color=(blue!45)}"
_ESCAPES = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
            "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}


def escape(text: object) -> str:
    """Escape a label or header coming from a results file."""
    return "".join(_ESCAPES.get(ch, ch) for ch in str("" if text is None else text))


def number(value: object, decimals: int) -> str:
    """Format a cell for LaTeX: integers stay integers, floats are rounded."""
    if value is None:
        return ""
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if value.is_integer() and abs(value) < 1e15:
            return str(int(value))
        return f"{value:.{decimals}f}"
    return escape(value)


@dataclass
class ChartSpec:
    """What to draw. Column names must exist in the table; values never come from here.

    Attributes:
        kind: ``line`` (training curves), ``bar``, ``matrix`` (confusion heat map)
            or ``table`` (booktabs).
        x: Column for the x axis / the row labels.
        series: Numeric columns to draw (``line``/``bar``) - one line or bar group each.
        columns: Columns to show, for ``kind="table"`` (default: all).
        legend: Optional nicer legend name per series column.
        x_label, y_label: Axis labels (already human-readable, not escaped).
        caption: Figure/table caption.
        decimals: Decimal places for printed numbers (default 3).
        width: ``\\linewidth`` fraction for the plot.
    """

    kind: str = "line"
    x: str = ""
    series: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    legend: dict[str, str] = field(default_factory=dict)
    x_label: str = ""
    y_label: str = ""
    caption: str = ""
    decimals: int = 3
    width: str = DEFAULT_WIDTH

    def label_for(self, column: str) -> str:
        return self.legend.get(column) or column


def validate_spec(spec: ChartSpec, table: ResultTable) -> list[str]:
    """Problems with ``spec`` against ``table`` (empty list = usable)."""
    problems: list[str] = []
    if spec.kind not in KINDS:
        return [f"kind must be one of {', '.join(KINDS)} (got {spec.kind!r})."]
    known = set(table.columns)
    available = ", ".join(table.columns)
    if spec.kind == "table":
        unknown = [c for c in spec.columns if c not in known]
        if unknown:
            problems.append(f"Unknown column(s) {unknown} - the table has: {available}.")
        return problems
    if spec.x not in known:
        problems.append(f"x must be a column of the table; {spec.x!r} is not. Available: {available}.")
    if not spec.series:
        problems.append("series must list at least one numeric column to plot.")
    for column in spec.series:
        if column not in known:
            problems.append(f"series column {column!r} does not exist. Available: {available}.")
        elif not table.is_numeric(column):
            problems.append(f"series column {column!r} is not numeric, so it cannot be plotted.")
        elif column == spec.x:
            problems.append(f"{column!r} is both the x axis and a series; choose different columns.")
    if len(spec.series) > MAX_SERIES:
        problems.append(f"At most {MAX_SERIES} series fit in one readable chart (got {len(spec.series)}).")
    if spec.kind == "line" and spec.x in known and not table.is_numeric(spec.x):
        problems.append(f"A line chart needs a numeric x axis; {spec.x!r} holds labels - use kind=\"bar\".")
    if spec.kind == "bar" and spec.x in known and len(table.rows) > MAX_BAR_GROUPS:
        problems.append(f"A bar chart with {len(table.rows)} groups is unreadable "
                        f"(limit {MAX_BAR_GROUPS}); use kind=\"table\".")
    return problems


def _pairs(table: ResultTable, spec: ChartSpec, column: str, symbolic: bool) -> str:
    xs, ys = table.values(spec.x), table.values(column)
    out = []
    for x, y in zip(xs, ys):
        if x is None or not isinstance(y, (int, float)):
            continue
        out.append(f"({escape(x) if symbolic else f'{x:g}'},{y:g})")
    if not out:
        raise ResultsError("Column '{column}' has no numeric values to plot.", column=column)
    return " ".join(out)


def _axis(options: list[str], body: str) -> str:
    joined = "".join(f"      {opt},\n" for opt in options if opt)
    return (f"\\begin{{tikzpicture}}\n  \\begin{{axis}}[\n{joined}    ]\n"
            f"{body}  \\end{{axis}}\n\\end{{tikzpicture}}")


def line_chart(table: ResultTable, spec: ChartSpec) -> str:
    """Training curves: one ``\\addplot`` per series, coordinates straight from the file."""
    xs = [v for v in table.values(spec.x) if isinstance(v, (int, float))]
    whole_numbers = all(float(x).is_integer() for x in xs)
    options = [f"width={spec.width}", "height=6.2cm",
               f"xlabel={{{escape(spec.x_label or spec.x)}}}", f"ylabel={{{escape(spec.y_label)}}}",
               # Epochs are whole numbers: never label an axis 1.5, 2.5 ...
               "xtick=data" if whole_numbers and len(xs) <= 15 else
               ("xtick distance=1" if whole_numbers and len(xs) <= 30 else ""),
               "grid=major", "legend pos=south east", "legend cell align=left",
               "every axis plot/.append style={line width=0.9pt}"]
    body = ""
    for column in spec.series:
        body += f"    \\addplot coordinates {{{_pairs(table, spec, column, symbolic=False)}}};\n"
        body += f"    \\addlegendentry{{{escape(spec.label_for(column))}}}\n"
    return _axis(options, body)


def bar_chart(table: ResultTable, spec: ChartSpec) -> str:
    """Grouped bars over label rows (models, classes, lighting conditions ...)."""
    groups = [escape(v) for v in table.values(spec.x) if v is not None]
    bars = max(1, len(groups) * max(1, len(spec.series)))
    crowded = len(groups) > 5 or max((len(g) for g in groups), default=0) > 9
    options = ["ybar", f"width={spec.width}", "height=6.2cm",
               f"bar width={max(3, min(12, 90 // bars))}pt",
               f"xlabel={{{escape(spec.x_label or spec.x)}}}", f"ylabel={{{escape(spec.y_label)}}}",
               f"symbolic x coords={{{','.join(groups)}}}", "xtick=data",
               # Bars are read by their height, so the axis must start at zero.
               "ymin=0",
               "x tick label style={rotate=30, anchor=north east}" if crowded else "",
               "ymajorgrids=true", "legend cell align=left",
               "legend style={at={(0.5,1.03)}, anchor=south, legend columns=-1, draw=none}",
               "enlarge x limits=0.12"]
    body = ""
    for column in spec.series:
        body += f"    \\addplot coordinates {{{_pairs(table, spec, column, symbolic=True)}}};\n"
        body += f"    \\addlegendentry{{{escape(spec.label_for(column))}}}\n"
    return _axis(options, body)


def confusion_matrix(table: ResultTable, spec: ChartSpec) -> str:
    """Heat map of a square count matrix, with the number printed in every cell."""
    classes = [escape(v) for v in table.values(spec.x)]
    size = len(spec.series)
    if len(classes) != size:
        raise ResultsError("A confusion matrix needs as many rows as plotted columns "
                           "({rows} rows, {columns} columns).", rows=len(classes), columns=size)
    if size > MAX_MATRIX_CLASSES:
        raise ResultsError("{count} classes do not fit in a readable matrix "
                           "(limit {limit}); plot a table instead.",
                           count=size, limit=MAX_MATRIX_CLASSES)
    points = []
    for row_at in range(size):
        for col_at, column in enumerate(spec.series):
            value = table.values(column)[row_at]
            if not isinstance(value, (int, float)):
                raise ResultsError("The matrix cell in row {row}, column '{column}' is not a number.",
                                   row=row_at + 1, column=column)
            points.append(f"({col_at},{size - 1 - row_at}) [{value:g}]")
    ticks = ",".join(str(i) for i in range(size))
    options = [f"width={spec.width}", f"height={spec.width}",     # square cells
               "colorbar", MATRIX_COLORMAP,
               "enlarge x limits={abs=0.5}", "enlarge y limits={abs=0.5}",   # show whole edge cells
               f"xlabel={{{escape(spec.x_label or 'Predicted class')}}}",
               f"ylabel={{{escape(spec.y_label or 'True class')}}}",
               f"xtick={{{ticks}}}", f"xticklabels={{{','.join(escape(spec.label_for(c)) for c in spec.series)}}}",
               f"ytick={{{ticks}}}", f"yticklabels={{{','.join(reversed(classes))}}}",
               "x tick label style={rotate=45, anchor=north east}",
               "nodes near coords={\\pgfmathprintnumber\\pgfplotspointmeta}",
               "every node near coord/.append style={font=" + ("\\small" if size <= 8 else "\\tiny")
               + ", anchor=center}",
               "point meta=explicit"]
    body = (f"    \\addplot[matrix plot*, point meta=explicit, mesh/cols={size}]\n"
            f"      coordinates {{{' '.join(points)}}};\n")
    return _axis(options, body)


def results_table(table: ResultTable, spec: ChartSpec) -> str:
    """A booktabs ``tabular`` of the chosen columns."""
    columns = spec.columns or table.columns
    alignment = "".join("l" if not table.is_numeric(c) else "r" for c in columns)
    head = " & ".join(f"\\textbf{{{escape(spec.label_for(c))}}}" for c in columns)
    lines = [f"\\begin{{tabular}}{{{alignment}}}", "  \\toprule", f"  {head} \\\\", "  \\midrule"]
    for row in table.rows:
        cells = [number(row[table.index(c)] if table.index(c) < len(row) else None, spec.decimals) for c in columns]
        lines.append("  " + " & ".join(cells) + r" \\")
    lines += ["  \\bottomrule", "\\end{tabular}"]
    return "\n".join(lines)


BUILDERS = {"line": line_chart, "bar": bar_chart, "matrix": confusion_matrix, "table": results_table}


def build(table: ResultTable, spec: ChartSpec) -> str:
    problems = validate_spec(spec, table)
    if problems:
        raise ResultsError(" ".join(problems))
    return BUILDERS[spec.kind](table, spec)


def float_block(body: str, caption: str, label: str, kind: str, placement: str = "htbp") -> str:
    """Wrap chart or tabular code in a ``figure``/``table`` float."""
    environment = "table" if kind == "table" else "figure"
    caption_line = f"  \\caption{{{caption.strip()}}}\n  \\label{{{label}}}\n"
    indented = "\n".join(f"  {ln}" if ln.strip() else ln for ln in body.splitlines())
    parts = [f"\\begin{{{environment}}}[{placement}]", "  \\centering"]
    if environment == "table":        # table captions go above the tabular
        parts.append(caption_line.rstrip("\n"))
        parts.append(indented)
    else:
        parts.append(indented)
        parts.append(caption_line.rstrip("\n"))
    parts.append(f"\\end{{{environment}}}")
    return "\n".join(parts)


def unique_label(prefix: str, stem: str, tex_sources: list[str], taken: set[str]) -> str:
    existing = {m.group(1) for src in tex_sources for m in re.finditer(r"\\label\{([^}]*)\}", src)} | taken
    label, n = f"{prefix}:{stem}", 2
    while label in existing:
        label, n = f"{prefix}:{stem}-{n}", n + 1
    taken.add(label)
    return label


def packages_for(kind: str) -> list[tuple[str, str, str]]:
    """``(package, options, extra preamble line)`` needed by a chart kind."""
    if kind == "table":
        return [("booktabs", "", "")]
    return [("pgfplots", "", "\\pgfplotsset{compat=1.18}")]

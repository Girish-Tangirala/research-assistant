"""Reading model-training and inference results into plain tables.

The files come from the user's own experiments (a CSV of per-epoch metrics, a
Keras/PyTorch history dumped as JSON, a scikit-learn ``classification_report``
printout, a confusion matrix) and usually live in the paper's local-only
``data/`` or ``supplementary/`` folder.

Every number a figure shows is parsed here, never retyped by the model: the LLM
only chooses *what* to plot (see :mod:`core.results_workflow`), so a chart can
never quietly disagree with the file it came from - the same rule that keeps
DOIs honest in :mod:`core.literature`.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from core.user_errors import UserMessage

SUFFIXES = (".csv", ".tsv", ".txt", ".log", ".json", ".xlsx", ".xlsm")
MAX_FILE_MB = 25
MAX_ROWS = 5000               # a training log with more rows is truncated, with a warning
MAX_FOLDER_FILES = 40
# Wrappers a saved history is often nested in: {"history": {"loss": [...]}}.
HISTORY_KEYS = ("history", "metrics", "results", "logs", "train_history", "scores")
EPOCH = "epoch"
_REPORT_ROW = re.compile(r"^\s*(?P<name>\S.*?)\s{2,}(?P<nums>[\d.]+(?:\s+[\d.]+)*)\s*$")
_NUMBER_ROW = re.compile(r"^[\s\[\]|,]*-?\d[\d.eE+\-\s,]*[\s\[\]|,]*$")


class ResultsError(UserMessage, ValueError):
    """A results file cannot be read or contains no usable numbers."""


@dataclass
class ResultTable:
    """A rectangular table of results, exactly as the file states it.

    Attributes:
        name: Short identifier shown to the user and to Claude.
        columns: Column headers (the first column is often a label, not a number).
        rows: One list of cells per row; numbers are ``float``/``int``, labels ``str``.
        source: The file the table was read from.
        note: How it was found (sheet name, JSON key, "classification report" ...).
    """

    name: str
    columns: list[str]
    rows: list[list[object]] = field(default_factory=list)
    source: str = ""
    note: str = ""

    def index(self, column: str) -> int:
        try:
            return self.columns.index(column)
        except ValueError as exc:
            raise ResultsError("{table}: no column named '{column}' (it has {columns})",
                               table=self.name, column=column,
                               columns=", ".join(self.columns)) from exc

    def values(self, column: str) -> list[object]:
        at = self.index(column)
        return [row[at] if at < len(row) else None for row in self.rows]

    def is_numeric(self, column: str) -> bool:
        seen = [v for v in self.values(column) if v is not None]
        return bool(seen) and all(isinstance(v, (int, float)) for v in seen)

    def numeric_columns(self) -> list[str]:
        return [c for c in self.columns if self.is_numeric(c)]

    def label_columns(self) -> list[str]:
        return [c for c in self.columns if not self.is_numeric(c)]

    def preview(self, max_rows: int = 6) -> str:
        """A few rows as text, for the prompt and the live log."""
        lines = [" | ".join(self.columns)]
        shown = self.rows if len(self.rows) <= max_rows else self.rows[: max_rows - 2] + [["..."]] + self.rows[-2:]
        for row in shown:
            lines.append(" | ".join(_cell_text(c) for c in row))
        return "\n".join(lines)


def _cell_text(value: object) -> str:
    if isinstance(value, float):
        return f"{value:g}"
    return "" if value is None else str(value)


def _as_number(text: str) -> object:
    """A cell as int/float when it looks like a plain number, else the text itself."""
    raw = text.strip().replace("−", "-")
    if not raw or raw.lower() in {"nan", "none", "null", "-", "n/a"}:
        return None
    try:
        if re.fullmatch(r"[+-]?\d+", raw):
            return int(raw)
        return float(raw)
    except ValueError:
        return text.strip()


def _clean_columns(names: list[str]) -> list[str]:
    """Non-empty, unique column names."""
    out: list[str] = []
    for position, name in enumerate(names, start=1):
        clean = " ".join(str(name or "").split()) or f"column {position}"
        base, n = clean, 2
        while clean in out:
            clean, n = f"{base} ({n})", n + 1
        out.append(clean)
    return out


def _table(name: str, columns: list[str], rows: list[list[object]], source: Path, note: str) -> ResultTable | None:
    rows = [r for r in rows if any(c is not None and c != "" for c in r)]
    if not rows or not columns:
        return None
    # One column of text is prose, not results; one column of numbers is a usable series.
    if len(columns) < 2 and not any(isinstance(c, (int, float)) for row in rows for c in row):
        return None
    return ResultTable(name=name, columns=_clean_columns(columns), rows=rows[:MAX_ROWS],
                       source=str(source), note=note)


# ---------------------------------------------------------------------- #
# Readers, one per format
# ---------------------------------------------------------------------- #
def _read_csv(path: Path) -> list[ResultTable]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    sample = text[:4096]
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        delimiter = "\t" if "\t" in sample else ";" if sample.count(";") > sample.count(",") else ","
    raw = [r for r in csv.reader(text.splitlines(), delimiter=delimiter) if r]
    if not raw:
        raise ResultsError("{name} has no rows.", name=path.name)
    header, body = raw[0], raw[1:]
    if not body or all(isinstance(_as_number(c), (int, float)) for c in header if c.strip()):
        header, body = [f"column {i}" for i in range(1, len(raw[0]) + 1)], raw
    rows = [[_as_number(c) for c in row] for row in body]
    table = _table(path.stem, header, rows, path, f"{len(rows)} rows read from {path.name}")
    if table is None:
        raise ResultsError("{name} has no table of results: expected columns of values "
                           "separated by commas, semicolons or tabs.", name=path.name)
    return [table]


def _read_excel(path: Path) -> list[ResultTable]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover - dependency is in requirements.txt
        raise ResultsError("Reading .xlsx files needs the openpyxl package "
                           "(pip install openpyxl). Save the sheet as CSV instead.") from exc
    book = load_workbook(path, read_only=True, data_only=True)
    tables = []
    try:
        for sheet in book.worksheets:
            raw = [[cell for cell in row] for row in sheet.iter_rows(values_only=True, max_row=MAX_ROWS + 1)]
            raw = [r for r in raw if any(c is not None and str(c).strip() for c in r)]
            if len(raw) < 2:
                continue
            header = [str(c) if c is not None else "" for c in raw[0]]
            rows = [[_as_number(str(c)) if not isinstance(c, (int, float)) else c for c in row] for row in raw[1:]]
            table = _table(f"{path.stem} · {sheet.title}", header, rows, path, f"sheet '{sheet.title}'")
            if table:
                tables.append(table)
    finally:
        book.close()
    if not tables:
        raise ResultsError("{name} has no sheet with a header row and data.", name=path.name)
    return tables


def _flatten_history(data: dict) -> dict[str, list]:
    """Keras-style ``{"loss": [...], "val_loss": [...]}``, possibly nested one level."""
    for key in HISTORY_KEYS:
        inner = data.get(key)
        if isinstance(inner, dict):
            data = inner
            break
    return {k: v for k, v in data.items() if isinstance(v, list) and v and
            all(isinstance(x, (int, float)) or x is None for x in v)}


def _read_json(path: Path) -> list[ResultTable]:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise ResultsError("{name} is not valid JSON ({problem}, line {line}).",
                           name=path.name, problem=exc.msg, line=exc.lineno) from exc

    if isinstance(data, dict):
        series = _flatten_history(data)
        if series:
            length = max(len(v) for v in series.values())
            columns = [EPOCH] + list(series)
            rows = [[i + 1] + [(v[i] if i < len(v) else None) for v in series.values()] for i in range(length)]
            table = _table(path.stem, columns, rows, path, f"{len(series)} metric(s) over {length} epochs")
            if table:
                return [table]
        # {"resnet50": {"accuracy": 0.9, ...}, ...} - one row per model
        nested = {k: v for k, v in data.items() if isinstance(v, dict)}
        if nested:
            keys: list[str] = []
            for inner in nested.values():
                keys += [k for k in inner if k not in keys]
            rows = [[name] + [inner.get(k) for k in keys] for name, inner in nested.items()]
            table = _table(path.stem, ["name"] + keys, rows, path, f"{len(nested)} entries with shared fields")
            if table:
                return [table]
        flat = {k: v for k, v in data.items() if isinstance(v, (int, float, str))}
        if flat:
            table = _table(path.stem, list(flat), [list(flat.values())], path, "single record")
            if table:
                return [table]

    if isinstance(data, list) and data and all(isinstance(x, dict) for x in data):
        keys = []
        for item in data:
            keys += [k for k in item if k not in keys]
        rows = [[item.get(k) for k in keys] for item in data]
        table = _table(path.stem, keys, rows, path, f"{len(data)} records")
        if table:
            return [table]

    raise ResultsError("{name}: no table of numbers found. Expected a history "
                       "(a loss/accuracy list), a list of records or one object per model.",
                       name=path.name)


def _read_report_text(text: str, path: Path) -> ResultTable | None:
    """A scikit-learn ``classification_report`` printout."""
    header = next((ln for ln in text.splitlines() if "precision" in ln and "recall" in ln), None)
    if header is None:
        return None
    columns = ["class"] + header.split()
    rows: list[list[object]] = []
    for line in text.splitlines()[text.splitlines().index(header) + 1:]:
        if not line.strip():
            continue
        match = _REPORT_ROW.match(line)
        if not match:
            if rows:
                break
            continue
        numbers = [_as_number(n) for n in match.group("nums").split()]
        name = match.group("name").strip()
        if name.lower() == "accuracy" and len(numbers) == 2:      # accuracy prints only f1 and support
            numbers = [None, None] + numbers
        rows.append([name] + numbers[: len(columns) - 1])
    return _table(f"{path.stem} · classification report", columns, rows, path, "classification report")


def _read_matrix_text(text: str, path: Path) -> ResultTable | None:
    """A confusion matrix printed as rows of numbers (with or without brackets)."""
    block: list[list[object]] = []
    best: list[list[object]] = []
    for line in text.splitlines() + [""]:
        stripped = line.strip()
        if stripped and _NUMBER_ROW.match(stripped) and any(ch.isdigit() for ch in stripped):
            cells = [_as_number(c) for c in re.split(r"[\s,]+", stripped.strip("[] |")) if c]
            block.append([c for c in cells if c is not None])
        else:
            if len(block) > len(best):
                best = block
            block = []
    widths = {len(r) for r in best}
    if len(best) < 2 or len(widths) != 1 or widths == {1}:
        return None
    size = len(best[0])
    columns = ["true \\ predicted"] + [f"class {i + 1}" for i in range(size)]
    rows = [[f"class {i + 1}"] + row for i, row in enumerate(best)]
    note = "confusion matrix" if size == len(best) else f"{len(best)}x{size} matrix of numbers"
    return _table(f"{path.stem} · {note}", columns, rows, path, note)


def _read_text(path: Path) -> list[ResultTable]:
    text = path.read_text(encoding="utf-8", errors="replace")
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    if "," in first or "\t" in first:      # a .txt/.log that is really a delimited table
        try:
            return _read_csv(path)
        except ResultsError:
            pass
    tables = [t for t in (_read_report_text(text, path), _read_matrix_text(text, path)) if t]
    if tables:
        return tables
    try:
        return _read_csv(path)
    except ResultsError as exc:
        raise ResultsError("{name}: no classification report, confusion matrix or table of "
                           "columns found.", name=path.name) from exc


READERS = {".csv": _read_csv, ".tsv": _read_csv, ".json": _read_json, ".txt": _read_text, ".log": _read_text,
           ".xlsx": _read_excel, ".xlsm": _read_excel}


# ---------------------------------------------------------------------- #
# Collecting files the user picked
# ---------------------------------------------------------------------- #
def read_file(path: Path) -> list[ResultTable]:
    """Read one results file. Raises :class:`ResultsError` with a plain reason."""
    if not path.is_file():
        raise ResultsError("{file} is not a file.", file=path)
    size_mb = path.stat().st_size / 1_000_000
    if size_mb > MAX_FILE_MB:
        raise ResultsError("{name} is {size} MB - too large to read (limit {limit} MB). "
                           "Export the summary you want to plot.",
                           name=path.name, size=f"{size_mb:.0f}", limit=MAX_FILE_MB)
    reader = READERS.get(path.suffix.lower())
    if reader is None:
        raise ResultsError("{name}: {kind} is not supported (supported: {known}).",
                           name=path.name, kind=path.suffix or "this file type",
                           known=", ".join(SUFFIXES))
    return reader(path)


def candidate_files(folder: Path) -> list[Path]:
    """Supported results files inside ``folder`` (recursively, newest folders first)."""
    found = [p for p in sorted(folder.rglob("*"))
             if p.is_file() and p.suffix.lower() in SUFFIXES and not p.name.startswith(".")
             and ".git" not in p.parts and p.name.lower() != "readme.md"]
    return found[:MAX_FOLDER_FILES]


def collect(paths: list[Path]) -> tuple[list[ResultTable], list[str]]:
    """Read every file (folders are scanned). Returns ``(tables, warnings)``.

    Unreadable files become warnings rather than failures, so one stray log in a
    folder does not stop the rest.
    """
    tables: list[ResultTable] = []
    warnings: list[str] = []
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            found = candidate_files(path)
            if not found:
                warnings.append(f"No CSV/JSON/TXT results files in {path}.")
            files += found
        else:
            files.append(path)
    for path in files:
        try:
            read = read_file(path)
        except ResultsError as exc:
            warnings.append(str(exc))
            continue
        for table in read:
            if len(table.rows) >= MAX_ROWS:
                warnings.append(f"{table.name}: only the first {MAX_ROWS} rows were read.")
            tables.append(table)
    if not tables:
        raise ResultsError("None of the chosen files contained a table of results. "
                           + " ".join(warnings))
    return tables, warnings


def summarise(tables: list[ResultTable]) -> str:
    """Compact description of every table, for the prompt (never the whole file)."""
    parts = []
    for n, table in enumerate(tables, start=1):
        ranges = []
        for column in table.numeric_columns():
            numbers = [v for v in table.values(column) if isinstance(v, (int, float))]
            if numbers:
                ranges.append(f"{column}: {min(numbers):g} to {max(numbers):g}")
        parts.append(f"<table id=\"{n}\" name=\"{table.name}\">\n"
                     f"Source file: {Path(table.source).name} ({table.note})\n"
                     f"Rows: {len(table.rows)}\n"
                     f"Columns: {', '.join(table.columns)}\n"
                     + (f"Ranges: {'; '.join(ranges)}\n" if ranges else "")
                     + f"First rows:\n{table.preview()}\n</table>")
    return "\n\n".join(parts)

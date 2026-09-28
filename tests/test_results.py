"""Results Figures & Tables: reading result files, drawing them and the end-to-end run."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from git import Repo

from core.figures import ensure_package
from core.results_data import (
    ResultsError, ResultTable, candidate_files, collect, read_file, summarise,
)
from core.results_latex import ChartSpec, build as draw, escape, float_block, number, validate_spec
from core.results_workflow import ResultsFigureWorkflow, parse_plan
from tests.conftest import MAIN_TEX
from tests.test_engine_integration import build, text_msg

HISTORY_CSV = (b"epoch,loss,val_loss,accuracy,val_accuracy\n"
               b"1,1.80,1.90,0.42,0.40\n2,1.20,1.35,0.61,0.58\n3,0.80,0.99,0.75,0.71\n"
               b"4,0.55,0.81,0.84,0.79\n5,0.41,0.76,0.90,0.83\n")
MODELS_CSV = (b"model;accuracy;f1\nResNet50;0.941;0.940\nResNet152;0.952;0.951\nVGG16;0.903;0.901\n")
REPORT_TXT = (b"              precision    recall  f1-score   support\n\n"
              b"       worn       0.94      0.91      0.92       120\n"
              b"     unworn       0.89      0.93      0.91       105\n\n"
              b"   accuracy                           0.93       225\n"
              b"  macro avg       0.93      0.92      0.92       225\n")
CONFUSION_TXT = b"[[109   8]\n [  6  98]]\n"


def write(folder: Path, name: str, data: bytes) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(data)      # bytes, so Windows does not turn \n into \r\r\n
    return path


# ---------------------------------------------------------------------- #
# Readers
# ---------------------------------------------------------------------- #
def test_reads_a_csv_training_log(tmp_path):
    table = read_file(write(tmp_path, "history.csv", HISTORY_CSV))[0]
    assert table.columns == ["epoch", "loss", "val_loss", "accuracy", "val_accuracy"]
    assert len(table.rows) == 5
    assert table.values("accuracy") == [0.42, 0.61, 0.75, 0.84, 0.90]
    assert table.numeric_columns() == table.columns
    assert table.rows[0][0] == 1 and isinstance(table.rows[0][0], int)


def test_reads_a_semicolon_csv_with_labels(tmp_path):
    table = read_file(write(tmp_path, "models.csv", MODELS_CSV))[0]
    assert table.columns == ["model", "accuracy", "f1"]
    assert table.label_columns() == ["model"] and table.numeric_columns() == ["accuracy", "f1"]
    assert table.values("model") == ["ResNet50", "ResNet152", "VGG16"]


def test_reads_a_keras_history_json(tmp_path):
    path = write(tmp_path, "h.json", json.dumps(
        {"history": {"loss": [1.6, 1.1, 0.8], "accuracy": [0.4, 0.6, 0.75]}}).encode())
    table = read_file(path)[0]
    assert table.columns == ["epoch", "loss", "accuracy"]
    assert table.values("epoch") == [1, 2, 3]          # epochs are added, not invented values
    assert table.values("loss") == [1.6, 1.1, 0.8]


def test_reads_one_record_per_model_json(tmp_path):
    path = write(tmp_path, "scores.json", json.dumps(
        {"ResNet50": {"accuracy": 0.94, "f1": 0.94}, "VGG16": {"accuracy": 0.90, "f1": 0.90}}).encode())
    table = read_file(path)[0]
    assert table.columns == ["name", "accuracy", "f1"]
    assert table.rows == [["ResNet50", 0.94, 0.94], ["VGG16", 0.90, 0.90]]


def test_reads_a_classification_report(tmp_path):
    table = read_file(write(tmp_path, "report.txt", REPORT_TXT))[0]
    assert table.columns == ["class", "precision", "recall", "f1-score", "support"]
    assert table.rows[0] == ["worn", 0.94, 0.91, 0.92, 120]
    accuracy = next(r for r in table.rows if r[0] == "accuracy")
    assert accuracy == ["accuracy", None, None, 0.93, 225]     # sklearn prints only f1 and support


def test_reads_a_confusion_matrix(tmp_path):
    table = read_file(write(tmp_path, "cm.txt", CONFUSION_TXT))[0]
    assert "confusion matrix" in table.note
    assert table.columns == ["true \\ predicted", "class 1", "class 2"]
    assert table.rows == [["class 1", 109, 8], ["class 2", 6, 98]]


def test_reads_an_excel_sheet(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "runs"
    for row in (["model", "accuracy"], ["ResNet50", 0.94], ["VGG16", 0.90]):
        sheet.append(row)
    path = tmp_path / "results.xlsx"
    book.save(path)
    table = read_file(path)[0]
    assert table.columns == ["model", "accuracy"] and table.values("accuracy") == [0.94, 0.90]
    assert "runs" in table.note


def test_unsupported_and_missing_files_explain_themselves(tmp_path):
    with pytest.raises(ResultsError, match="not supported"):
        read_file(write(tmp_path, "model.h5", b"\x89HDF"))
    with pytest.raises(ResultsError, match="not a file"):
        read_file(tmp_path / "nope.csv")
    with pytest.raises(ResultsError, match="no classification report"):
        read_file(write(tmp_path, "notes.txt", b"just some prose about the experiment\n"))


def test_collect_scans_a_folder_and_keeps_going_past_a_bad_file(tmp_path):
    folder = tmp_path / "data" / "run7"
    write(folder, "history.csv", HISTORY_CSV)
    write(folder, "report.txt", REPORT_TXT)
    write(folder, "broken.json", b"{not json")
    write(folder, "weights.h5", b"\x89HDF")           # not a candidate at all
    assert [p.name for p in candidate_files(folder)] == ["broken.json", "history.csv", "report.txt"]
    tables, warnings = collect([tmp_path / "data"])
    assert {t.source.endswith("history.csv") for t in tables} == {True, False}
    assert any("not valid JSON" in w for w in warnings)
    assert len(tables) == 2


def test_collect_refuses_when_nothing_could_be_read(tmp_path):
    write(tmp_path, "broken.json", b"{not json")
    with pytest.raises(ResultsError, match="None of the chosen files"):
        collect([tmp_path])


def test_summary_names_columns_but_is_not_the_whole_file(tmp_path):
    tables, _ = collect([write(tmp_path, "history.csv", HISTORY_CSV)])
    text = summarise(tables)
    assert "Columns: epoch, loss, val_loss, accuracy, val_accuracy" in text
    assert "accuracy: 0.42 to 0.9" in text
    assert text.count("\n") < 20


# ---------------------------------------------------------------------- #
# Drawing
# ---------------------------------------------------------------------- #
def make_table() -> ResultTable:
    return ResultTable("models", ["model", "accuracy", "f1"],
                       [["ResNet50", 0.9412, 0.940], ["VGG16", 0.903, 0.9014]], "models.csv")


def test_escaping_and_number_formatting():
    assert escape("top_5 accuracy (%)") == r"top\_5 accuracy (\%)"
    assert escape("a & b #1") == r"a \& b \#1"
    assert number(0.94123, 3) == "0.941" and number(120, 3) == "120"
    assert number(3.0, 3) == "3" and number(None, 3) == ""


def test_spec_must_name_real_numeric_columns():
    table = make_table()
    assert validate_spec(ChartSpec(kind="bar", x="model", series=["accuracy"]), table) == []
    problems = validate_spec(ChartSpec(kind="bar", x="model", series=["auc"]), table)
    assert "does not exist" in problems[0] and "model, accuracy, f1" in problems[0]
    problems = validate_spec(ChartSpec(kind="bar", x="accuracy", series=["model"]), table)
    assert any("not numeric" in p for p in problems)
    problems = validate_spec(ChartSpec(kind="line", x="model", series=["accuracy"]), table)
    assert any("needs a numeric x axis" in p for p in problems)
    assert "kind must be one of" in validate_spec(ChartSpec(kind="pie", x="model"), table)[0]


def test_line_chart_uses_the_files_numbers(tmp_path):
    table = read_file(write(tmp_path, "history.csv", HISTORY_CSV))[0]
    code = draw(table, ChartSpec(kind="line", x="epoch", series=["accuracy", "val_accuracy"],
                                 legend={"accuracy": "Training"}, x_label="Epoch", y_label="Accuracy"))
    assert r"\begin{axis}" in code and "xtick=data" in code      # 5 whole epochs -> integer ticks
    assert "(1,0.42) (2,0.61) (3,0.75) (4,0.84) (5,0.9)" in code
    assert r"\addlegendentry{Training}" in code and r"\addlegendentry{val\_accuracy}" in code


def test_bar_chart_starts_at_zero_and_uses_symbolic_labels():
    code = draw(make_table(), ChartSpec(kind="bar", x="model", series=["accuracy", "f1"]))
    assert "ymin=0" in code                          # a truncated bar axis would exaggerate differences
    assert "symbolic x coords={ResNet50,VGG16}" in code
    assert "(ResNet50,0.9412)" in code and "(VGG16,0.9014)" in code


def test_table_is_booktabs_with_aligned_columns():
    code = draw(make_table(), ChartSpec(kind="table", x="model", columns=["model", "accuracy", "f1"],
                                        decimals=3))
    assert r"\begin{tabular}{lrr}" in code
    assert r"\toprule" in code and r"\midrule" in code and r"\bottomrule" in code
    assert r"ResNet50 & 0.941 & 0.940 \\" in code


def test_confusion_matrix_needs_a_square_block(tmp_path):
    table = read_file(write(tmp_path, "cm.txt", CONFUSION_TXT))[0]
    spec = ChartSpec(kind="matrix", x="true \\ predicted", series=["class 1", "class 2"])
    code = draw(table, spec)
    assert "matrix plot*" in code and "mesh/cols=2" in code
    assert "(0,1) [109] (1,1) [8] (0,0) [6] (1,0) [98]" in code       # first row drawn at the top
    assert "colormap={conf}" in code
    with pytest.raises(ResultsError, match="as many rows as plotted columns"):
        draw(table, ChartSpec(kind="matrix", x="true \\ predicted", series=["class 1"]))


def test_float_block_puts_table_captions_above_and_figure_captions_below():
    figure = float_block("CHART", "A chart.", "fig:x", "line")
    assert figure.index("CHART") < figure.index(r"\caption{A chart.}")
    assert figure.startswith(r"\begin{figure}[htbp]") and figure.endswith(r"\end{figure}")
    table = float_block("TABULAR", "A table.", "tab:x", "table")
    assert table.index(r"\caption{A table.}") < table.index("TABULAR")
    assert r"\label{tab:x}" in table and table.startswith(r"\begin{table}[htbp]")


def test_ensure_package_is_idempotent():
    assert ensure_package(r"\documentclass{a}\usepackage{pgfplots}", "pgfplots") is None
    assert ensure_package(r"\documentclass{a}\usepackage[table]{xcolor}", "xcolor") is None
    added = ensure_package(MAIN_TEX, "pgfplots", "", r"\pgfplotsset{compat=1.18}")
    assert added.index(r"\usepackage{pgfplots}") > added.index(r"\usepackage{amsmath}")
    assert added.index(r"\pgfplotsset{compat=1.18}") < added.index(r"\begin{document}")


def test_plan_parsing():
    plan = parse_plan("table: 2\nkind: bar\nx: model\nseries: accuracy, f1\nlegend: f1 = F1 score\n")
    assert plan == {"table": "2", "kind": "bar", "x": "model", "series": "accuracy, f1",
                    "legend": "f1 = F1 score"}


# ---------------------------------------------------------------------- #
# End-to-end
# ---------------------------------------------------------------------- #
def test_results_figure_end_to_end(tmp_path, git_project):
    remote, _ = git_project
    data = write(tmp_path / "Desktop" / "run7", "history.csv", HISTORY_CSV)
    prompts = []

    def responder(system, messages, tools=None, max_tokens=None):
        prompts.append(messages[0]["content"])
        return text_msg("<plan>\ntable: 1\nkind: line\nx: epoch\n"
                        "series: accuracy, val_accuracy\nlegend: val_accuracy = Validation\n"
                        "x_label: Epoch\ny_label: Accuracy\n</plan>\n"
                        "<caption>Accuracy per epoch.</caption>"
                        "<sentence>Figure~\\ref{fig:history} shows the accuracy.</sentence>")

    engine, approver = build(tmp_path, remote, SimpleNamespace(create=responder))
    try:
        result = ResultsFigureWorkflow(engine, files=[str(data)], section_title="Method").run()
    finally:
        approver.stop()

    assert "Columns: epoch, loss, val_loss, accuracy, val_accuracy" in prompts[0]
    assert "1.8" in prompts[0]                       # a preview of real values was shown
    feature = next(h.name for h in Repo(remote).heads if h.name.startswith("agent/"))
    tex = Repo(remote).git.show(f"{feature}:main.tex")
    assert r"\usepackage{pgfplots}" in tex and r"\pgfplotsset{compat=1.18}" in tex
    assert r"\begin{tikzpicture}" in tex and r"\caption{Accuracy per epoch.}" in tex
    assert "(1,0.42) (2,0.61) (3,0.75) (4,0.84) (5,0.9)" in tex
    assert r"\addlegendentry{Validation}" in tex
    assert r"Figure~\ref{fig:history} shows the accuracy." in tex
    assert tex.index(r"\label{fig:history}") < tex.index(r"\bibliographystyle")
    assert result.success


def test_a_plan_naming_a_missing_column_is_repaired(tmp_path, git_project):
    remote, _ = git_project
    data = write(tmp_path / "run", "models.csv", MODELS_CSV)
    answers = iter([
        "<plan>\ntable: 1\nkind: bar\nx: model\nseries: auc\n</plan><caption>Scores.</caption>",
        "<plan>\ntable: 1\nkind: bar\nx: model\nseries: accuracy, f1\n</plan><caption>Scores.</caption>",
    ])
    problems = []

    def responder(system, messages, tools=None, max_tokens=None):
        if len(messages) > 1:
            problems.append(messages[-1]["content"])
        return text_msg(next(answers))

    engine, approver = build(tmp_path, remote, SimpleNamespace(create=responder))
    try:
        ResultsFigureWorkflow(engine, files=[str(data)], section_title="Method",
                              reference_sentence=False).run()
    finally:
        approver.stop()
    assert "does not exist" in problems[0] and "model, accuracy, f1" in problems[0]
    feature = next(h.name for h in Repo(remote).heads if h.name.startswith("agent/"))
    tex = Repo(remote).git.show(f"{feature}:main.tex")
    assert "(ResNet50,0.941)" in tex and "ymin=0" in tex


def test_rejecting_the_change_leaves_the_paper_alone(tmp_path, git_project):
    remote, _ = git_project
    data = write(tmp_path / "run", "models.csv", MODELS_CSV)
    engine, approver = build(tmp_path, remote, SimpleNamespace(create=None), approve=False)
    try:
        ResultsFigureWorkflow(engine, files=[str(data)], section_title="Method", kind="table",
                              x="model", series="model, accuracy, f1", caption="Scores.",
                              reference_sentence=False).run()
    finally:
        approver.stop()
    assert not Repo(tmp_path / "clone").is_dirty(untracked_files=True)
    assert [h.name for h in Repo(remote).heads] == ["master"]


def test_a_hand_made_table_needs_no_claude_sign_in():
    assert ResultsFigureWorkflow.requires_llm({"files": ["a.csv"]})
    assert ResultsFigureWorkflow.requires_llm({"kind": "table", "x": "model", "series": "accuracy",
                                               "caption": "Scores."})     # sentence still wanted
    assert not ResultsFigureWorkflow.requires_llm({"kind": "table", "x": "model", "series": "accuracy",
                                                   "caption": "Scores.", "reference_sentence": False})


def test_the_agent_never_writes_into_the_data_folder(tmp_path, git_project):
    """Results are read from data/, but the figure is written to the manuscript only."""
    remote, clone = git_project
    engine, approver = build(tmp_path, remote, SimpleNamespace(create=None), approve=False)
    approver.stop()
    engine.paper.git.sync()
    engine.refresh_protection()
    data = write(engine.paper.root / "data", "history.csv", HISTORY_CSV)
    tables, _ = collect([data])
    assert len(tables[0].rows) == 5                     # reading is allowed
    with pytest.raises(Exception, match="read-only"):
        engine.paper.ensure_writable("data/history.csv")

"""Finding the TeX toolchain even when the inherited PATH is stale."""

import sys

import pytest

import config


@pytest.mark.skipif(sys.platform != "win32", reason="Windows install locations")
def test_finds_miktex_outside_inherited_path(tmp_path, monkeypatch):
    bin_dir = tmp_path / "Programs" / "MiKTeX" / "miktex" / "bin" / "x64"
    bin_dir.mkdir(parents=True)
    (bin_dir / "pdflatex.exe").write_bytes(b"")
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("PDFLATEX_PATH", raising=False)
    monkeypatch.setattr(config, "_registry_path", lambda: "")
    assert config._which("PDFLATEX_PATH", "pdflatex").lower() == str(bin_dir / "pdflatex.exe").lower()


def test_registry_path_is_used(tmp_path, monkeypatch):
    tool = tmp_path / ("newtool.exe" if sys.platform == "win32" else "newtool")
    tool.write_bytes(b"")
    tool.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setattr(config, "_registry_path", lambda: str(tmp_path))
    monkeypatch.setattr(config, "_tex_install_dirs", lambda: [])
    assert config._which("NEWTOOL_PATH", "newtool").lower() == str(tool).lower()


def test_explicit_env_wins(monkeypatch):
    monkeypatch.setenv("PDFLATEX_PATH", r"D:\TeX\pdflatex.exe")
    assert config._which("PDFLATEX_PATH", "pdflatex") == r"D:\TeX\pdflatex.exe"

"""Shared fixtures: a sample LaTeX project backed by a local bare Git remote."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from git import Actor, Repo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

MAIN_TEX = r"""\documentclass{article}
\usepackage{amsmath}
\title{Graph Neural Networks for \emph{Protein} Folding}
\begin{document}
\maketitle

\section{Introduction}
\label{sec:intro}
Protein folding is hard~\cite{jumper2021}. We use graph networks \citep{kipf2017,velickovic2018}
with loss $\mathcal{L} = \sum_i \ell_i$ which is 50\% faster.
% TODO: this comment mentions $x$ and \cite{commented}
As shown in Eq.~\eqref{eq:loss}, the objective is convex.
\begin{equation}
  \label{eq:loss}
  \mathcal{L}(\theta) = \frac{1}{N}\sum_{i=1}^{N} \|y_i - f_\theta(x_i)\|^2
\end{equation}

\subsection{Contributions}
\begin{itemize}
  \item A new model \cite{missingkey}.
  \item Experiments on CASP.
\end{itemize}

\section{Method}
\input{sections/method}

\bibliographystyle{plain}
\bibliography{refs}
\end{document}
"""

METHOD_TEX = r"""Our method builds on message passing \cite{gilmer2017}.
"""

REFS_BIB = r"""@article{jumper2021,
  author = {Jumper, John and others},
  title = {Highly accurate protein structure prediction with {AlphaFold}},
  journal = {Nature},
  year = {2021},
  doi = {10.1038/s41586-021-03819-2}
}

@inproceedings{kipf2017,
  author = "Kipf, Thomas and Welling, Max",
  title = {Semi-Supervised Classification with Graph Convolutional Networks},
  booktitle = {ICLR},
  year = 2017
}

@inproceedings{velickovic2018,
  author = {Veli{\v{c}}kovi{\'c}, Petar},
  title = {Graph Attention Networks},
  booktitle = {ICLR},
  year = {2018},
  doi = {https://doi.org/10.48550/arXiv.1710.10903}
}

@article{gilmer2017,
  author = {Gilmer, Justin},
  title = {Neural Message Passing},
  year = {2017}
}

@misc{unused2020,
  title = {Never cited}
}

@comment{ this is ignored }
"""


def _write_project(root: Path) -> None:
    (root / "sections").mkdir(parents=True, exist_ok=True)
    (root / "main.tex").write_text(MAIN_TEX, encoding="utf-8")
    (root / "sections" / "method.tex").write_text(METHOD_TEX, encoding="utf-8")
    (root / "refs.bib").write_text(REFS_BIB, encoding="utf-8")


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    root = tmp_path / "paper"
    _write_project(root)
    return root


@pytest.fixture
def git_project(tmp_path: Path) -> tuple[Path, Path]:
    """Return ``(remote_bare_path, seed_clone_path)`` with one initial commit on master."""
    remote = tmp_path / "remote.git"
    Repo.init(remote, bare=True, initial_branch="master")
    seed = tmp_path / "seed"
    repo = Repo.init(seed, initial_branch="master")
    _write_project(seed)
    repo.index.add(["main.tex", "sections/method.tex", "refs.bib"])
    actor = Actor("Test", "test@example.com")
    repo.index.commit("Initial", author=actor, committer=actor)
    repo.create_remote("origin", str(remote))
    repo.git.push("origin", "master")
    return remote, seed

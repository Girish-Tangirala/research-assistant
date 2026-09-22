"""Settings shared by every external program the app starts (git, pdflatex, synctex ...)."""

from __future__ import annotations

import subprocess
import sys

# The packaged app has no console, so on Windows each console program would flash a
# black window of its own. This flag suppresses that (it is 0, i.e. no-op, elsewhere).
NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

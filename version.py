"""The app's version and where its updates are published.

``scripts/release.py`` bumps ``__version__`` and publishes a GitHub release tagged
``v<version>`` on ``UPDATE_REPO``; every installed copy checks that repository's latest
release at start-up (``core/updater.py``).
"""

__version__ = "1.1.0"
UPDATE_REPO = "Girish-Tangirala/research-assistant"   # owner/name on github.com

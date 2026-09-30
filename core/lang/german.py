"""The German catalogue, assembled from the parts (each stays under the line limit)."""

from __future__ import annotations

from core.lang import de_detail, de_forms, de_menu, de_status

CATALOGUE: dict[str, str] = {**de_menu.CATALOGUE, **de_forms.CATALOGUE, **de_status.CATALOGUE,
                             **de_detail.CATALOGUE}

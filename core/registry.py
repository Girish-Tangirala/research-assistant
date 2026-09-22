"""Workflows shown in the app, in tab order."""

from __future__ import annotations

from core.asset_workflows import AddFiguresWorkflow, AddReferencesWorkflow
from core.workflows import (
    BaseWorkflow, CitationAuditWorkflow, CustomAgentWorkflow, LiteratureReviewWorkflow, SafeEditWorkflow,
)

WORKFLOWS: dict[str, type[BaseWorkflow]] = {
    cls.name: cls
    for cls in (
        SafeEditWorkflow,
        LiteratureReviewWorkflow,
        AddFiguresWorkflow,
        AddReferencesWorkflow,
        CitationAuditWorkflow,
        CustomAgentWorkflow,
    )
}

"""Git errors, in their own module so :mod:`core.git_sync` can use them too."""

from __future__ import annotations
from core.user_errors import UserMessage


class GitOperationError(UserMessage, RuntimeError):
    """A Git operation failed; the message is safe to show to the user."""


class GitAuthError(GitOperationError):
    """The Git host rejected (or requires) credentials."""

    def __init__(self, message: str, host: str, **fields: object) -> None:
        super().__init__(message, **fields)
        self.host = host

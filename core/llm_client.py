"""Thin, streaming wrapper around the Anthropic Python SDK (1.x).

Every request:

* streams (long LaTeX inputs/outputs would otherwise risk HTTP timeouts), and
  forwards text / thinking-summary deltas to the live log in real time;
* uses adaptive thinking with summarized display so the GUI can show the
  agent's reasoning;
* enables top-level automatic prompt caching so the growing ReAct transcript is
  re-read from cache on every step;
* opts into server-side refusal fallbacks (``fallbacks="default"``) unless
  disabled in config;
* maps SDK exceptions to a single :class:`LLMError` hierarchy with messages a
  researcher can act on.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from typing import Any

import anthropic
from anthropic.types.beta import BetaMessage

from config import LLMSettings

FALLBACK_BETA = "server-side-fallback-2026-07-01"

TextCallback = Callable[[str], None]


class LLMError(RuntimeError):
    """Base class for LLM failures surfaced to the user."""


class LLMAuthError(LLMError):
    """The stored API key was rejected - the user must sign in again."""


class LLMRefusal(LLMError):
    """The model (and any fallback) declined the request."""


class LLMTruncated(LLMError):
    """The response hit ``max_tokens`` before finishing."""


class LLMClient:
    """Streaming Claude client used by the agent engine and workflows."""

    def __init__(
        self,
        settings: LLMSettings,
        api_key: str | None = None,
        on_text: TextCallback | None = None,
        on_thinking: TextCallback | None = None,
        client: anthropic.Anthropic | None = None,
    ) -> None:
        self.settings = settings
        self._on_text = on_text
        self._on_thinking = on_thinking
        if client is None and not api_key:
            raise LLMAuthError("Not signed in to Claude. Use Accounts → Claude to sign in.")
        self._client = client or anthropic.Anthropic(api_key=api_key, max_retries=3)

    # ------------------------------------------------------------------ #
    # Core request
    # ------------------------------------------------------------------ #
    def create(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: Sequence[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> BetaMessage:
        """Send one streamed request and return the final message.

        Args:
            system: Stable system prompt (kept byte-identical for caching).
            messages: Conversation so far; never mutated here.
            tools: Tool definitions (custom and server tools) for agentic turns.
            max_tokens: Override for the configured output cap.

        Raises:
            LLMRefusal: ``stop_reason == "refusal"`` after fallbacks.
            LLMError: any API / network failure, with an actionable message.
        """
        kwargs: dict[str, Any] = {
            "model": self.settings.model,
            "max_tokens": max_tokens or self.settings.max_tokens,
            "system": system,
            "messages": messages,
            "thinking": {"type": "adaptive", "display": "summarized"},
            "output_config": {"effort": self.settings.effort},
            "cache_control": {"type": "ephemeral"},
        }
        if tools:
            kwargs["tools"] = list(tools)
        if self.settings.use_server_fallbacks:
            kwargs["betas"] = [FALLBACK_BETA]
            kwargs["fallbacks"] = "default"

        try:
            with self._client.beta.messages.stream(**kwargs) as stream:
                for event in stream:
                    if event.type != "content_block_delta":
                        continue
                    delta = event.delta
                    if delta.type == "text_delta" and self._on_text:
                        self._on_text(delta.text)
                    elif delta.type == "thinking_delta" and self._on_thinking:
                        self._on_thinking(delta.thinking)
                message = stream.get_final_message()
        except anthropic.AuthenticationError as exc:
            raise LLMAuthError(
                "Claude rejected the stored API key. Sign in again via Accounts → Claude."
            ) from exc
        except anthropic.PermissionDeniedError as exc:
            raise LLMError(f"Claude API permission denied: {exc.message}") from exc
        except anthropic.NotFoundError as exc:
            raise LLMError(
                f"Model {self.settings.model!r} not found or not enabled for this key."
            ) from exc
        except anthropic.RateLimitError as exc:
            retry_after = exc.response.headers.get("retry-after", "?")
            raise LLMError(f"Rate limited by the Claude API (retry after {retry_after}s).") from exc
        except anthropic.BadRequestError as exc:
            hint = ""
            if "web_search" in str(exc.message):
                hint = (" - web search may not be enabled for your organization "
                        "(Claude Console → Settings → Privacy), or turn off 'Use Claude web search'.")
            raise LLMError(f"Claude API rejected the request: {exc.message}{hint}") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(
                f"Claude API error {exc.status_code}: {exc.message} (request id: {exc.request_id})"
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("Could not reach the Claude API - check your network connection.") from exc

        if message.stop_reason == "refusal":
            details = message.stop_details
            category = getattr(details, "category", None) if details else None
            raise LLMRefusal(f"The model declined this request (category: {category or 'unspecified'}).")
        return message


def text_of(message: BetaMessage) -> str:
    """Concatenate all text blocks of a message."""
    return "".join(block.text for block in message.content if block.type == "text")


def extract_tagged(text: str, tag: str) -> str | None:
    """Return the content of the last ``<tag>...</tag>`` block in ``text``."""
    matches = re.findall(rf"<{tag}>\s*(.*?)\s*</{tag}>", text, flags=re.DOTALL)
    return matches[-1] if matches else None

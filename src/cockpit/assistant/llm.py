"""The language model behind the assistant, behind a small interface.

The rest of the code only needs one thing: send a conversation, get text as it
comes, then the complete reply. Tests plug a scripted model in the same place.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

# Dollars per million tokens: input, output, cache write (5 minutes), cache read.
# Read on platform.claude.com/docs/en/about-claude/pricing on 02/10/2026; an estimate
# of the cost is derived from them, the invoice remains the reference.
MODELS: dict[str, dict] = {
    "claude-sonnet-5-5": {"label": "Sonnet 5.5", "prices": (2, 10, 2.5, 0.2)},
    "claude-haiku-4-5-20251001": {"label": "Haiku 4.5", "prices": (1, 5, 1.25, 0.1)},
    "claude-opus-5-5": {"label": "Opus 5.5", "prices": (4, 20, 5, 0.2)},
}
DEFAULT_MODEL = "claude-sonnet-5-5"
WEB_SEARCH_PRICE = Decimal("0.01")  # dollars per search
WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}
MILLION = Decimal(1_000_000)


@dataclass
class Usage:
    input_tokens: int = 0  # not counting what was read from or written to the cache
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    web_searches: int = 0


def cost(model: str, usage: Usage) -> Decimal:
    """Estimated cost of one call, in dollars."""
    spec = MODELS.get(model)
    if spec is None:
        return Decimal(0)
    price_in, price_out, price_write, price_read = (Decimal(str(p)) for p in spec["prices"])
    tokens = (
        usage.input_tokens * price_in
        + usage.output_tokens * price_out
        + usage.cache_write_tokens * price_write
        + usage.cache_read_tokens * price_read
    ) / MILLION
    return tokens + usage.web_searches * WEB_SEARCH_PRICE


@dataclass
class Reply:
    content: list[dict]  # content blocks, to be sent back unchanged on the next call
    stop_reason: str
    usage: Usage


class LLMError(Exception):
    """The call failed. `kind`: 'cle', 'quota', 'reseau', 'requete', 'service'."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


class LLM(Protocol):
    def stream(
        self,
        *,
        api_key: str,
        model: str,
        system: list[dict],
        messages: list[dict],
        tools: list[dict],
        max_tokens: int,
    ) -> Iterator[str | Reply]:
        """Yield the text as it is written, then the complete reply, once."""


class AnthropicLLM:
    retries = 2  # the SDK waits and tries again on overload or a dropped connection

    def __init__(self, http_client: object | None = None):
        self._http_client = http_client  # tests plug a canned transport in here

    def stream(
        self,
        *,
        api_key: str,
        model: str,
        system: list[dict],
        messages: list[dict],
        tools: list[dict],
        max_tokens: int,
    ) -> Iterator[str | Reply]:
        import anthropic

        client = anthropic.Anthropic(
            api_key=api_key,
            max_retries=self.retries,
            timeout=180.0,
            http_client=self._http_client,
        )
        try:
            with client.messages.stream(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
                tools=tools,
                # The fixed part (instructions, tools) and the conversation so far are
                # re-read from the cache at a tenth of the price on the next call.
                cache_control={"type": "ephemeral"},
            ) as stream:
                for event in stream:
                    if event.type == "content_block_delta" and event.delta.type == "text_delta":
                        yield event.delta.text
                message = stream.get_final_message()
        except anthropic.AuthenticationError as exc:
            raise LLMError(
                "cle", "La clé d'API a été refusée. La vérifier ou la remplacer."
            ) from exc
        except anthropic.PermissionDeniedError as exc:
            raise LLMError("cle", f"Accès refusé par l'API : {_detail(exc)}") from exc
        except anthropic.RateLimitError as exc:
            raise LLMError(
                "quota", "Limite de débit ou de dépense atteinte côté API. Réessayer plus tard."
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("reseau", "L'API est injoignable. Vérifier la connexion.") from exc
        except anthropic.BadRequestError as exc:
            raise LLMError("requete", f"Requête refusée par l'API : {_detail(exc)}") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError("service", f"Erreur de l'API ({exc.status_code}). Réessayer.") from exc

        usage = message.usage
        searches = getattr(getattr(usage, "server_tool_use", None), "web_search_requests", 0)
        yield Reply(
            content=[block.model_dump(mode="json", exclude_none=True) for block in message.content],
            stop_reason=message.stop_reason or "end_turn",
            usage=Usage(
                input_tokens=usage.input_tokens or 0,
                output_tokens=usage.output_tokens or 0,
                cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
                cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
                web_searches=searches or 0,
            ),
        )


def _detail(exc: Exception) -> str:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
    return str(exc)

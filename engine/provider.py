"""Thin provider interface around the model call.

Kept deliberately small: the agent loop owns gating, budgets and event
emission, and this module owns nothing but "turn messages + tools into a
response". That makes the loop testable against a scripted fake.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ModelConfig:
    """Models the brief asked for, by their real identifiers.

    The plan named "Sonnet 5.5" and "Opus 5.5"; the shipping models are
    `claude-sonnet-5` and `claude-opus-5`, so those are used here.
    """
    loop_model: str = field(
        default_factory=lambda: os.environ.get("FL_LOOP_MODEL", "claude-sonnet-5"))
    capstone_model: str = field(
        default_factory=lambda: os.environ.get("FL_CAPSTONE_MODEL", "claude-opus-5"))
    max_tokens: int = 16000
    effort: str = field(default_factory=lambda: os.environ.get("FL_EFFORT", "high"))

    def for_experiment(self, order: int, n_experiments: int) -> str:
        return self.capstone_model if order == n_experiments else self.loop_model


class Provider(Protocol):
    def complete(self, *, model: str, system: str, messages: list[dict[str, Any]],
                 tools: list[dict[str, Any]], max_tokens: int,
                 effort: str) -> Any: ...


class AnthropicProvider:
    def __init__(self, api_key: str | None = None):
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

    def complete(self, *, model: str, system: str, messages: list[dict[str, Any]],
                 tools: list[dict[str, Any]], max_tokens: int = 16000,
                 effort: str = "high") -> Any:
        # Streaming because these turns are long and tool-heavy; the helper
        # hands back the assembled message so the loop stays readable.
        with self._client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            tools=tools,
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
        ) as stream:
            return stream.get_final_message()


class ScriptedProvider:
    """Replays canned responses. Used by the engine tests, and by `--dry-run`."""

    def __init__(self, responses: list[Any]):
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def complete(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if not self._responses:
            raise RuntimeError("ScriptedProvider ran out of responses")
        return self._responses.pop(0)

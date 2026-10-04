"""Model clients for the shared LLMAgent harness, plus the token/cost ledger.

A client is anything with ``complete(system, messages) -> str`` (see
``agents.llm_agent.ModelClient``). ``AnthropicClient`` wraps the Anthropic
Messages API; ``DryRunClient`` returns a fixed abstention without network
access. Both report usage to a ``TokenLedger``, which logs calls and raises
``SpendLimitExceeded`` when its estimated USD limit is exceeded. Batch
collection combines per-episode ledgers for a stage spend guard.
"""
from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import dataclass, field
from typing import Callable, Optional

# USD per million tokens (input, output), public list prices. Matched by the
# longest key that prefixes the model id, so dated ids resolve too.
PRICES_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-4": (15.0, 75.0),
    "claude-sonnet-4": (3.0, 15.0),
    "claude-haiku-4": (1.0, 5.0),
    "claude-3-7-sonnet": (3.0, 15.0),
    "claude-3-5-sonnet": (3.0, 15.0),
    "claude-3-5-haiku": (0.8, 4.0),
    "claude-3-opus": (15.0, 75.0),
}
DEFAULT_SPEND_LIMIT_USD = 20.0
DEFAULT_TEMPERATURE = 1.0
API_KEY_ENV = "ANTHROPIC_API_KEY"


class SpendLimitExceeded(RuntimeError):
    """Estimated spend passed the limit; the stage must stop."""


def price_for(model: str, usd_in: Optional[float] = None, usd_out: Optional[float] = None) -> tuple[float, float]:
    """(input, output) USD per million tokens for ``model``. Explicit overrides
    win; otherwise the price table; an unknown model is an error rather than a
    silent guess, because the number gates real spend."""
    if usd_in is not None and usd_out is not None:
        return float(usd_in), float(usd_out)
    for key in sorted(PRICES_USD_PER_MTOK, key=len, reverse=True):
        if model.startswith(key):
            return PRICES_USD_PER_MTOK[key]
    raise ValueError(
        f"no price known for model {model!r}; pass --usd-per-mtok-in and --usd-per-mtok-out "
        f"(known prefixes: {', '.join(sorted(PRICES_USD_PER_MTOK))})"
    )


@dataclass
class TokenLedger:
    """Cumulative token spend for one stage, with a hard USD stop."""

    usd_per_mtok_in: float
    usd_per_mtok_out: float
    limit_usd: float = DEFAULT_SPEND_LIMIT_USD
    log: Optional[Callable[[str], None]] = field(default=lambda line: print(line, file=sys.stderr, flush=True))
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0

    @property
    def cost_usd(self) -> float:
        return self.estimate(self.input_tokens, self.output_tokens)

    def estimate(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * self.usd_per_mtok_in + output_tokens * self.usd_per_mtok_out) / 1e6

    def record(self, input_tokens: int, output_tokens: int, label: str = "") -> None:
        """Add one call's usage, log the running total, stop if over the limit."""
        self.calls += 1
        self.input_tokens += int(input_tokens)
        self.output_tokens += int(output_tokens)
        if self.log is not None:
            self.log(
                f"[spend] call {self.calls}{' ' + label if label else ''}: "
                f"+{int(input_tokens)} in / +{int(output_tokens)} out; cumulative "
                f"{self.input_tokens} in / {self.output_tokens} out = ${self.cost_usd:.4f} "
                f"(limit ${self.limit_usd:.2f})"
            )
        if self.cost_usd > self.limit_usd:
            raise SpendLimitExceeded(
                f"STOP: estimated spend ${self.cost_usd:.4f} exceeds the ${self.limit_usd:.2f} limit "
                f"after {self.calls} model calls ({self.input_tokens} input / {self.output_tokens} output tokens)"
            )

    def snapshot(self) -> dict:
        return {
            "model_calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "estimated_cost_usd": round(self.cost_usd, 6),
            "usd_per_mtok_in": self.usd_per_mtok_in,
            "usd_per_mtok_out": self.usd_per_mtok_out,
            "spend_limit_usd": self.limit_usd,
        }


class DryRunClient:
    """Deterministic no-network client that emits an abstaining conclusion."""

    def __init__(
        self,
        model: str,
        ledger: TokenLedger,
        *,
        hypothesis_ids: list[str],
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = 2048,
    ) -> None:
        if not 0.0 <= temperature <= 1.0:
            raise ValueError("temperature must be in [0, 1]")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.ledger = ledger
        self.hypothesis_ids = list(hypothesis_ids)
        self.call_log: list[dict] = []

    def complete(self, system: str, messages: list[dict]) -> str:
        reply = json.dumps({
            "kind": "conclude",
            "contributing_hypotheses": [],
            "dominant_cause": None,
            "makes_target_claim": False,
            "confidence": None,
            "evidence_cited": [],
            "beliefs": {hypothesis_id: 0.5 for hypothesis_id in self.hypothesis_ids},
            "reasoning": "stub",
        }, separators=(",", ":"))
        input_tokens = math.ceil(
            (len(system) + sum(len(message["content"]) for message in messages)) / 4
        )
        output_tokens = math.ceil(len(reply) / 4)
        self.call_log.append({
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "stop_reason": "dry_run",
        })
        self.ledger.record(input_tokens, output_tokens, label=self.model)
        return reply


class AnthropicClient:
    """``complete(system, messages)`` over the Anthropic Messages API.

    The key is read from ``ANTHROPIC_API_KEY`` by the SDK; it is never passed
    on the command line or written anywhere. Every call's usage goes to the
    ledger before the text is returned, so a call that tips the stage over the
    spend limit still gets counted and then stops the stage.
    """

    def __init__(
        self,
        model: str,
        ledger: TokenLedger,
        *,
        max_tokens: int = 2048,
        temperature: float = DEFAULT_TEMPERATURE,
        client=None,
    ) -> None:
        if not 0.0 <= temperature <= 1.0:
            raise ValueError("temperature must be in [0, 1]")
        if client is None:
            if not os.environ.get(API_KEY_ENV):
                raise RuntimeError(f"{API_KEY_ENV} is not set in the environment")
            import anthropic

            client = anthropic.Anthropic()
        self.model = model
        self.ledger = ledger
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._client = client
        self.call_log: list[dict] = []

    def complete(self, system: str, messages: list[dict]) -> str:
        response = self._client.messages.create(
            model=self.model,
            system=system,
            messages=[{"role": m["role"], "content": m["content"]} for m in messages],
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )
        text = "".join(getattr(block, "text", "") for block in response.content)
        usage = response.usage
        self.call_log.append({
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "stop_reason": getattr(response, "stop_reason", None),
        })
        self.ledger.record(usage.input_tokens, usage.output_tokens, label=self.model)
        return text

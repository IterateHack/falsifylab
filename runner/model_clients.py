"""Model clients for the shared LLMAgent harness, plus the token/cost ledger.

A client is anything with ``complete(system, messages) -> str`` (see
``agents.llm_agent.ModelClient``). ``AnthropicClient`` wraps the Anthropic
Messages API; ``DryRunClient`` returns a fixed abstention without network
access. Both report usage to a ``TokenLedger``, which logs calls and raises
``SpendLimitExceeded`` when its estimated USD limit is exceeded. Before each
call, both also reserve the call's worst-case cost and refuse to make a call
that could cross the limit, so a ledger's spend never exceeds its limit.
Batch collection combines per-episode ledgers for a stage spend guard.
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
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-4": (1.0, 5.0),
    "claude-3-7-sonnet": (3.0, 15.0),
    "claude-3-5-sonnet": (3.0, 15.0),
    "claude-3-5-haiku": (0.8, 4.0),
    "claude-3-opus": (15.0, 75.0),
}
DEFAULT_SPEND_LIMIT_USD = 20.0
DEFAULT_TEMPERATURE = 1.0
DEFAULT_PROVIDER_RETRIES = 1
API_KEY_ENV = "ANTHROPIC_API_KEY"
# Per-message allowance for role and turn framing tokens in the input bound.
MESSAGE_FRAMING_TOKENS = 16


class ProviderRefusal(RuntimeError):
    pass


def sampling_settings(model: str, temperature: float) -> dict:
    sent = not (model == "claude-sonnet-5" or model.startswith("claude-sonnet-5-"))
    return {"model": model, "temperature": temperature if sent else None,
            "sampling_params_sent": sent}


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
    """Cumulative token spend for one episode or stage, with a hard USD stop."""

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

    def reserve(self, input_tokens: int, output_tokens: int, label: str = "") -> None:
        """Stop before a call whose worst-case usage could take spend past the limit."""
        worst_case = self.estimate(input_tokens, output_tokens)
        if self.cost_usd + worst_case > self.limit_usd:
            raise SpendLimitExceeded(
                f"STOP before call {self.calls + 1}{' ' + label if label else ''}: estimated spend "
                f"${self.cost_usd:.4f} plus the call's worst case ${worst_case:.4f} "
                f"({int(input_tokens)} input / {int(output_tokens)} output tokens) would exceed "
                f"the ${self.limit_usd:.2f} limit"
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


def reserve_in_ledgers(
    ledgers: list[Optional[TokenLedger]], input_tokens: int, output_tokens: int, label: str = "",
) -> None:
    seen: list[TokenLedger] = []
    for ledger in ledgers:
        if ledger is not None and not any(ledger is other for other in seen):
            seen.append(ledger)
            ledger.reserve(input_tokens, output_tokens, label=label)


class InputTokenBound:
    """Upper bound on a call's input tokens.

    Assumes a token covers at least one UTF-8 byte (byte-level BPE) and allows
    ``MESSAGE_FRAMING_TOKENS`` per message. When the prompt extends the last
    one, the bound is the last call's reported input tokens plus the bytes
    added since; otherwise it bounds the whole prompt.
    """

    def __init__(self) -> None:
        self._prompt: Optional[list[tuple[str, str]]] = None
        self._input_tokens = 0

    @staticmethod
    def _prompt_parts(system: str, messages: list[dict]) -> list[tuple[str, str]]:
        return [("system", system)] + [(m["role"], m["content"]) for m in messages]

    def bound(self, system: str, messages: list[dict]) -> int:
        prompt = self._prompt_parts(system, messages)
        previous = self._prompt
        if previous is not None and prompt[:len(previous)] == previous:
            added, base = prompt[len(previous):], self._input_tokens
        else:
            added, base = prompt, 0
        return base + sum(
            len(content.encode("utf-8")) + MESSAGE_FRAMING_TOKENS for _, content in added
        )

    def observe(self, system: str, messages: list[dict], input_tokens: int) -> None:
        self._prompt = self._prompt_parts(system, messages)
        self._input_tokens = int(input_tokens)


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
        self.sampling = sampling_settings(model, temperature)
        self.temperature = self.sampling["temperature"]
        self.max_tokens = max_tokens
        self.ledger = ledger
        self.hypothesis_ids = list(hypothesis_ids)
        self.call_log: list[dict] = []
        self.provider_retries = 0
        self._input_bound = InputTokenBound()

    def complete(self, system: str, messages: list[dict]) -> str:
        reserve_in_ledgers(
            [self.ledger], self._input_bound.bound(system, messages), self.max_tokens,
            label=self.model,
        )
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
        self._input_bound.observe(system, messages, input_tokens)
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
    spend limit still gets counted and then stops the stage. Each call first
    reserves its worst case (input bound plus ``max_tokens`` output) in both
    ledgers and is not made if that could cross either limit.
    """

    def __init__(
        self,
        model: str,
        ledger: TokenLedger,
        *,
        max_tokens: int = 2048,
        temperature: float = DEFAULT_TEMPERATURE,
        provider_retries: int = DEFAULT_PROVIDER_RETRIES,
        stage_ledger: Optional[TokenLedger] = None,
        client=None,
    ) -> None:
        if not 0.0 <= temperature <= 1.0:
            raise ValueError("temperature must be in [0, 1]")
        if provider_retries < 0:
            raise ValueError("provider_retries must be nonnegative")
        if client is None:
            if not os.environ.get(API_KEY_ENV):
                raise RuntimeError(f"{API_KEY_ENV} is not set in the environment")
            import anthropic

            client = anthropic.Anthropic()
        self.model = model
        self.ledger = ledger
        self.max_tokens = max_tokens
        self.sampling = sampling_settings(model, temperature)
        self.temperature = self.sampling["temperature"]
        self.provider_retries = provider_retries
        self.stage_ledger = stage_ledger
        self._client = client
        self.call_log: list[dict] = []
        self._input_bound = InputTokenBound()

    def _record_usage(self, input_tokens: int, output_tokens: int) -> None:
        episode_error = stage_error = None
        try:
            self.ledger.record(input_tokens, output_tokens, label=self.model)
        except SpendLimitExceeded as exc:
            episode_error = exc
        if self.stage_ledger is not None and self.stage_ledger is not self.ledger:
            try:
                self.stage_ledger.record(input_tokens, output_tokens, label=self.model)
            except SpendLimitExceeded as exc:
                stage_error = exc
        if stage_error is not None:
            raise stage_error
        if episode_error is not None:
            raise episode_error

    def complete(self, system: str, messages: list[dict]) -> str:
        for _ in range(self.provider_retries + 1):
            reserve_in_ledgers(
                [self.stage_ledger, self.ledger], self._input_bound.bound(system, messages),
                self.max_tokens, label=self.model,
            )
            response = self._client.messages.create(
                model=self.model,
                system=system,
                messages=[{"role": m["role"], "content": m["content"]} for m in messages],
                max_tokens=self.max_tokens,
                **({"extra_body": {"temperature": self.temperature}}
                   if self.sampling["sampling_params_sent"] else {}),
            )
            text = "".join(getattr(block, "text", "") for block in response.content)
            usage = response.usage
            self._input_bound.observe(system, messages, usage.input_tokens)
            self.call_log.append({
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "stop_reason": getattr(response, "stop_reason", None),
            })
            self._record_usage(usage.input_tokens, usage.output_tokens)
            if response.stop_reason != "refusal":
                return text
        raise ProviderRefusal("Anthropic returned stop_reason=refusal")

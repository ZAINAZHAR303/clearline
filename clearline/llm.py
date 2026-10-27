"""Power layer: tiered Nemotron with a risk-proportional reasoning budget.

The tiering is the point. One model call for everything forfeits the "best use
of NVIDIA Nemotron" award, which is the largest single prize in the event.

  NANO   high-volume normalisation and extraction, reasoning off
  SUPER  the Resolver/Critic loop -- tool calling and real multi-step reasoning
  ULTRA  the Adjudicator, contested cases only

Budget policy (docs/measurements.md): spend reasoning in proportion to
stakes, log what was spent, and show the histogram in the demo.

NOTE ON THE BUDGET PARAMETER
----------------------------
Nemotron 3 supports granular reasoning-budget control, but the exact request
field differs per serving stack. Rather than invent one, this module expresses
the budget as (a) a system directive and (b) a max_tokens ceiling, and exposes
REASONING_PARAM so you can switch to the native field once you have confirmed
it on the build.nvidia.com model card. Everything downstream is unaffected.
"""

from __future__ import annotations

import json
import os
from enum import Enum
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# Set to the native field name (e.g. "max_thinking_tokens") once confirmed on
# the model card; leave empty to use the max_tokens + directive approach.
REASONING_PARAM = os.environ.get("NEMOTRON_REASONING_PARAM", "").strip()


class Tier(str, Enum):
    NANO = "nano"
    SUPER = "super"
    ULTRA = "ultra"


BASE_BUDGET = {"LOW": 1, "MED": 2, "HIGH": 4}
BUDGET_CEILING = 6

# Nemotron 3.x is a reasoning model: it emits its chain of thought into a
# SEPARATE `reasoning_content` field, but those tokens are still billed against
# max_tokens. A budget sized for the answer alone gets entirely consumed by
# reasoning and returns EMPTY content -- which looks like a JSON parse failure
# and is not one. Measured: a trivial prompt spent 65 reasoning tokens for 7 of
# answer, so a real prompt needs room in the thousands.
_TOKENS_PER_UNIT = 1600
_MIN_TOKENS = 1200

# Per-tier ceilings. Measured on nemotron-3.5-super-vl: the router spent 1093
# reasoning tokens and 103 seconds deciding a name was not generic, and the
# critic truncated at 3200. Extraction does not need deliberation; adjudication
# does. Capping the cheap tiers is what keeps a run inside its time budget.
_TIER_CEILING = {"nano": 900, "super": 5200, "ultra": 9000}

# Reasoning toggle, established by measurement rather than documentation
# (scripts/ has the A/B; docs/measurements.md has the table). On
# nemotron-3.5-lightning-30b-a3b, asked for a small JSON extraction:
#
#   plain                                  900 reasoning tokens, EMPTY content
#   "/no_think" system directive           429 reasoning tokens
#   chat_template_kwargs thinking=False      0 reasoning tokens   <-- this one
#
# The system directive only halves deliberation, which is why the nano tier
# kept exhausting its budget. The chat-template flag turns it off outright.
THINKING_OFF = {"chat_template_kwargs": {"thinking": False}}


def budget_for(risk_tier: str, critic_rejections: int = 0) -> int:
    """Risk tier and critic pushback drive the budget. This is the measurable
    claim behind the Nemotron pitch, so it is a pure function and easy to test."""
    budget = BASE_BUDGET.get(risk_tier.upper(), 1)
    budget = budget * (1 + 0.5 * critic_rejections)
    return int(min(budget, BUDGET_CEILING))


def _model_for(tier: Tier) -> str:
    override = os.environ.get(f"NEMOTRON_MODEL_{tier.name}")
    if override:
        return override
    base = os.environ.get("NEMOTRON_MODEL")
    if not base:
        raise RuntimeError("NEMOTRON_MODEL is not set -- see .env.example")
    return base


_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        base_url = os.environ.get("MODEL_BASE_URL")
        api_key = os.environ.get("MODEL_API_KEY")
        if not base_url or not api_key:
            raise RuntimeError(
                "MODEL_BASE_URL and MODEL_API_KEY must be set, both from the SAME "
                "route -- see .env.example"
            )
        # 180s: a local Meterless/Nightshift route can take minutes to load a model.
        _client = OpenAI(base_url=base_url, api_key=api_key, timeout=180.0)
    return _client


def fake_mode() -> bool:
    """Deterministic canned responses, so the orchestration can be exercised
    and tested without a model or a network. Also the fixture the offline test
    suite runs against."""
    return os.environ.get("CLEARLINE_FAKE_LLM", "").lower() in {"1", "true", "yes"}


def complete_json(
    *,
    tier: Tier,
    system: str,
    user: str,
    budget: int = 1,
    trace=None,
    agent: str = "?",
    fake: dict | None = None,
    max_repair: int = 2,
) -> dict[str, Any]:
    """One structured call. Returns parsed JSON.

    A parse failure is repaired by feeding the validation error back, not by
    throwing -- agents must degrade, not crash.
    """
    if fake_mode():
        if fake is None:
            raise RuntimeError(f"CLEARLINE_FAKE_LLM is on but {agent} supplied no fake response")
        if trace:
            trace.event("llm.call", agent=agent, tier=tier.value, budget=budget, faked=True)
        return fake

    model = _model_for(tier)
    max_tokens = max(_MIN_TOKENS, _TOKENS_PER_UNIT * budget)
    max_tokens = min(max_tokens, _TIER_CEILING[tier.value])
    # Provider-specific fields travel in extra_body; the OpenAI client
    # rejects them as top-level keyword arguments.
    extra_body: dict[str, Any] = {}
    if REASONING_PARAM:
        extra_body[REASONING_PARAM] = max_tokens
    if tier is Tier.NANO:
        # Pure extraction and normalisation. Deliberation here is waste, so the
        # whole budget goes to the answer.
        directive = "Answer directly."
        extra_body.update(THINKING_OFF)
    elif budget <= 3:
        directive = "Think carefully and check your reasoning."
    else:
        directive = ("Think very carefully. Consider alternatives and challenge "
                     "your first conclusion.")

    messages = [
        {"role": "system", "content": f"{system}\n\n{directive}\nReply with JSON only."},
        {"role": "user", "content": user},
    ]

    last_error = ""
    attempt = 0
    budget_retries = 0
    # Repair attempts and budget retries are counted separately. A truncated
    # call is not a model mistake, and letting it consume the repair allowance
    # meant the one fix that works -- turning deliberation off -- was tried on
    # the final iteration and never got to run.
    while attempt <= max_repair and budget_retries <= 2:
        if trace:
            trace.event(
                "llm.call", agent=agent, tier=tier.value, model=model,
                budget=budget, max_tokens=max_tokens, attempt=attempt,
            )
        reply = _get_client().chat.completions.create(
            model=model, messages=messages, max_tokens=max_tokens,
            temperature=0.2 if tier is Tier.NANO else 0.6,
            **({"extra_body": extra_body} if extra_body else {}),
        )
        choice = reply.choices[0]
        text = (choice.message.content or "").strip()

        # Actual reasoning tokens spent. This is the measurement behind the
        # "spend reasoning in proportion to risk" claim -- real usage data, not
        # an estimate, and the input to the demo's budget histogram.
        reasoning_tokens = None
        details = getattr(reply.usage, "completion_tokens_details", None)
        if details is not None:
            reasoning_tokens = getattr(details, "reasoning_tokens", None)
        if trace:
            trace.event(
                "llm.result", agent=agent, tier=tier.value,
                finish_reason=choice.finish_reason,
                completion_tokens=getattr(reply.usage, "completion_tokens", None),
                reasoning_tokens=reasoning_tokens, max_tokens=max_tokens,
                # Present but null when deliberation is disabled, so coalesce
                # before slicing rather than relying on a default.
                reasoning=((getattr(choice.message, "model_extra", None) or {})
                           .get("reasoning_content") or "")[:400],
            )

        # Truncated mid-reasoning: the budget is the problem, so retrying at the
        # same size cannot help. Escalate it instead of burning an attempt.
        if choice.finish_reason == "length" and not text:
            last_error = "reasoning consumed the whole token budget before any answer"
            budget_retries += 1
            already_direct = "chat_template_kwargs" in extra_body
            escalated = min(max_tokens * 2, _TIER_CEILING[tier.value])

            # Escalate ONCE. If a second call still spends the whole budget
            # deliberating, more tokens is a gamble while disabling reasoning
            # is near-certain -- and each truncated call costs ~40 seconds, so
            # climbing the ceiling one doubling at a time is the expensive way
            # to arrive at the same answer.
            if not already_direct and (budget_retries >= 2 or escalated == max_tokens):
                extra_body.update(THINKING_OFF)
                max_tokens = max(max_tokens, _MIN_TOKENS)
                if trace:
                    trace.event("llm.degraded", agent=agent, attempt=attempt,
                                reason="budget spent on reasoning twice; answering directly")
                continue

            if already_direct or escalated == max_tokens:
                break  # nothing left to try
            if trace:
                trace.event("llm.budget_exhausted", agent=agent, attempt=attempt,
                            max_tokens=max_tokens, next_max_tokens=escalated)
            max_tokens = escalated
            continue

        try:
            return json.loads(_strip_fences(text))
        except json.JSONDecodeError as error:
            last_error = str(error)
            if trace:
                trace.event("llm.parse_error", agent=agent, attempt=attempt, error=last_error)
            messages.append({"role": "assistant", "content": text[:1000]})
            messages.append({
                "role": "user",
                "content": f"That was not valid JSON ({last_error}). Reply with JSON only.",
            })
            attempt += 1

    raise RuntimeError(f"{agent}: could not obtain valid JSON after {max_repair + 1} attempts: {last_error}")


def _strip_fences(text: str) -> str:
    """Models wrap JSON in code fences and sometimes emit a reasoning preamble.
    Take the outermost JSON object."""
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            candidate = part.removeprefix("json").strip()
            if candidate.startswith("{"):
                return candidate
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start != -1 and end > start else text

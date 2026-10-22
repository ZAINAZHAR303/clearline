"""Power layer: tiered Nemotron with a risk-proportional reasoning budget.

The tiering is the point. One model call for everything forfeits the "best use
of NVIDIA Nemotron" award, which is the largest single prize in the event.

  NANO   high-volume normalisation and extraction, reasoning off
  SUPER  the Resolver/Critic loop -- tool calling and real multi-step reasoning
  ULTRA  the Adjudicator, contested cases only

Budget policy (BUILD-PLAN.md section 6): spend reasoning in proportion to
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
_TOKENS_PER_UNIT = 700


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
    max_tokens = _TOKENS_PER_UNIT * budget
    directive = (
        "Think briefly." if budget <= 1
        else "Think carefully and check your reasoning." if budget <= 3
        else "Think very carefully. Consider alternatives and challenge your first conclusion."
    )
    extra: dict[str, Any] = {}
    if REASONING_PARAM:
        extra[REASONING_PARAM] = max_tokens

    messages = [
        {"role": "system", "content": f"{system}\n\n{directive}\nReply with JSON only."},
        {"role": "user", "content": user},
    ]

    last_error = ""
    for attempt in range(max_repair + 1):
        if trace:
            trace.event(
                "llm.call", agent=agent, tier=tier.value, model=model,
                budget=budget, max_tokens=max_tokens, attempt=attempt,
            )
        reply = _get_client().chat.completions.create(
            model=model, messages=messages, max_tokens=max_tokens,
            temperature=0.2 if tier is Tier.NANO else 0.6, **extra,
        )
        text = (reply.choices[0].message.content or "").strip()
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

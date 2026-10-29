"""
FLEETI GPT-5 agentic orchestrator (OpenAI Responses API).

A single tool-calling loop. Cross-turn memory lives server-side in an OpenAI
**Conversation** (the endpoint passes its id) — we send only the new user message
each turn, and the conversation also carries reasoning across the within-turn tool
calls. A stable instructions+tools prefix + prompt_cache_key maximize prompt caching.
"""

import os
import json
import asyncio
import logging
from datetime import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

try:
    from openai import OpenAI  # type: ignore
except Exception:  # pragma: no cover
    OpenAI = None

from FleetiAgent.prompts import build_orchestrator_instructions
from FleetiAgent.tools import TOOL_DEFINITIONS, ToolContext, execute_tool
from FleetiAgent.turn_trace import TurnTrace, trace_enabled
from FleetiCommon import parse_user_utc_offset

load_dotenv()
logger = logging.getLogger(__name__)
usage_logger = logging.getLogger("FleetiAgent.usage")

MAX_TOOL_TURNS = 6


def _usage_from(resp: Any):
    """Extract (input, cached_input, output, reasoning) token counts from a Responses result."""
    u = getattr(resp, "usage", None)
    if not u:
        return 0, 0, 0, 0
    inp = getattr(u, "input_tokens", 0) or 0
    out = getattr(u, "output_tokens", 0) or 0
    itd = getattr(u, "input_tokens_details", None)
    cached = (getattr(itd, "cached_tokens", 0) or 0) if itd else 0
    otd = getattr(u, "output_tokens_details", None)
    reasoning = (getattr(otd, "reasoning_tokens", 0) or 0) if otd else 0
    return inp, cached, out, reasoning


def _estimate_cost_usd(input_t: int, cached_t: int, output_t: int) -> float:
    """Rough per-turn cost using configurable per-1M prices (defaults = gpt-5.2)."""
    price_in = float(os.getenv("FLEETI_PRICE_INPUT_PER_M", "1.75"))
    price_cached = float(os.getenv("FLEETI_PRICE_CACHED_INPUT_PER_M", "0.175"))
    price_out = float(os.getenv("FLEETI_PRICE_OUTPUT_PER_M", "14.0"))
    uncached = max(input_t - cached_t, 0)
    return (uncached * price_in + cached_t * price_cached + output_t * price_out) / 1_000_000


def _error_text(exc: Exception) -> str:
    """Lower-cased error text, including the OpenAI error body message when present."""
    msg = str(exc).lower()
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        msg += " " + str(body.get("message", "")).lower()
    return msg


def _is_conversation_error(exc: Exception) -> bool:
    """True when a call failed because the conversation id is missing/invalid/expired."""
    msg = _error_text(exc)
    return "conversation" in msg and any(
        s in msg for s in ("not found", "does not exist", "no conversation", "invalid")
    )


def _is_stuck_tool_state(exc: Exception) -> bool:
    """
    True when the conversation has a dangling function_call with no matching output
    (e.g. a prior report turn short-circuited before recording the tool output). Recoverable
    by abandoning the conversation and starting a fresh one — same path as a missing conversation.
    """
    return "no tool output found for function call" in _error_text(exc)


@dataclass
class AgentResult:
    """Outcome of one /chat turn, shaped so the endpoint can build the response."""
    text: str = ""
    report_payload: Optional[Dict[str, Any]] = None
    used_fleet_query: bool = False
    last_fleet_query: str = ""
    last_fleet_rows: List[Dict[str, Any]] = field(default_factory=list)
    selected_collections: List[str] = field(default_factory=list)
    error: bool = False
    conversation_invalid: bool = False  # endpoint should re-seed a fresh conversation and retry
    export_url: Optional[str] = None  # download link when the model exported results to xlsx
    usage: Dict[str, int] = field(default_factory=dict)  # token usage of this turn (measurement)


class FleetiAgent:
    def __init__(self) -> None:
        api_key = os.getenv("OPENAI_API_KEY")
        self.client = OpenAI(api_key=api_key) if (api_key and OpenAI is not None) else None
        # Full GPT-5 orchestrator. Falls back to OPENAI_MODEL so it picks up the
        # account's configured model (e.g. gpt-5.2) even if the dedicated var is unset.
        self.model = os.getenv("FLEETI_ORCHESTRATOR_MODEL") or "gpt-5.2"
        # "low" by default to keep reasoning-token cost down; override via FLEETI_REASONING_EFFORT.
        self.reasoning_effort = os.getenv("FLEETI_REASONING_EFFORT") or "low"

    # ----- OpenAI call (run off the event loop) -----
    def _create(self, conversation_id: str, **kwargs: Any) -> Any:
        return self.client.responses.create(
            model=self.model,
            instructions=build_orchestrator_instructions(),
            tools=TOOL_DEFINITIONS,
            reasoning={"effort": self.reasoning_effort},
            conversation=conversation_id,
            prompt_cache_key=conversation_id,  # pin cache routing per session
            truncation="auto",                 # bound very long sessions to the context window
            **kwargs,
        )

    async def run(
        self,
        user_message: str,
        *,
        conversation_id: str,
        mongo_db: str,
        sub_tenant_id: Optional[str],
        base_url: str,
        authorization: Optional[str],
        time_zone: Optional[str],
        remove_sub_tenant_match: bool,
        turn_index: int = 0,
    ) -> AgentResult:
        if self.client is None:
            return AgentResult(text="The assistant is not configured correctly.", error=True)

        ctx = ToolContext(
            mongo_db=mongo_db,
            sub_tenant_id=sub_tenant_id,
            base_url=base_url,
            authorization=authorization,
            time_zone=time_zone,
            remove_sub_tenant_match=remove_sub_tenant_match,
            user_question=user_message,
            conversation_id=conversation_id,
            turn_index=turn_index,
        )

        logger.info(
            "▶ turn start | conv=%s | tz=%s | q=%r",
            conversation_id, time_zone or "UTC", (user_message or "")[:200],
        )

        # Inject the current date/time in the USER'S timezone per-turn. Kept out of the cached
        # instructions prefix (so caching still hits); only the new user message + this note are new.
        now_user = datetime.now(parse_user_utc_offset(time_zone))
        time_note = (
            f"Current date & time: {now_user.strftime('%Y-%m-%d %H:%M:%S')} "
            f"(timezone: {time_zone or 'UTC'})"
        )
        input_items: List[Dict[str, Any]] = [
            {"role": "developer", "content": time_note},
            {"role": "user", "content": user_message},
        ]

        # Per-turn debug trace (test-only; no-op unless FLEETI_TURN_TRACE is enabled).
        trace = TurnTrace(trace_enabled())
        trace.set_meta(
            timestamp=now_user.isoformat(timespec="seconds"),
            conversation_id=conversation_id,
            model=self.model,
            reasoning=self.reasoning_effort,
            mongo_db=mongo_db,
            sub_tenant_id=sub_tenant_id,
            time_zone=time_zone or "UTC",
            question=user_message,
        )
        trace.section("USER QUESTION")
        trace.block("question", user_message or "")
        trace.block("input sent to model (turn 1)", input_items)

        # Per-turn token accounting (measurement only — no behavior change).
        usage = {"calls": 0, "input": 0, "cached": 0, "output": 0, "reasoning": 0}

        def _track(resp: Any) -> None:
            i, c, o, r = _usage_from(resp)
            usage["calls"] += 1
            usage["input"] += i
            usage["cached"] += c
            usage["output"] += o
            usage["reasoning"] += r

        def _log_usage() -> None:
            est = _estimate_cost_usd(usage["input"], usage["cached"], usage["output"])
            pct = (100 * usage["cached"] // usage["input"]) if usage["input"] else 0
            usage_logger.info(
                "💰 token usage | calls=%d input=%d cached=%d (%d%%) output=%d reasoning=%d | est=$%.4f",
                usage["calls"], usage["input"], usage["cached"], pct,
                usage["output"], usage["reasoning"], est,
            )

        def _trace_totals() -> str:
            est = _estimate_cost_usd(usage["input"], usage["cached"], usage["output"])
            return (
                f"TOTALS: calls={usage['calls']} input={usage['input']} cached={usage['cached']} "
                f"output={usage['output']} reasoning={usage['reasoning']} est=${est:.4f}"
            )

        def _trace_model_call(index: int, resp: Any) -> None:
            if not trace.enabled:
                return
            i, c, o, r = _usage_from(resp)
            trace.model_call(index, {"input": i, "cached": c, "output": o, "reasoning": r}, resp)

        try:
            resp = await asyncio.to_thread(self._create, conversation_id, input=input_items)
            _track(resp)
            call_no = 1
            _trace_model_call(call_no, resp)

            for _ in range(MAX_TOOL_TURNS):
                function_calls = [o for o in (resp.output or []) if getattr(o, "type", None) == "function_call"]
                if not function_calls:
                    break

                tool_outputs: List[Dict[str, Any]] = []
                for fc in function_calls:
                    try:
                        call_args = json.loads(fc.arguments or "{}")
                    except (TypeError, ValueError):
                        call_args = {}
                    result = await execute_tool(fc.name, call_args, ctx)
                    if trace.enabled:
                        trace.section(f"TOOL CALL: {fc.name}")
                        trace.block("arguments", call_args)
                        if fc.name == "get_query_context":
                            trace.block("schema context returned to model", result)
                        elif fc.name == "run_fleet_query":
                            trace.block("exact Mongo query executed", ctx.last_fleet_query or "(none)")
                            trace.block("query result returned to model", result)
                            if isinstance(result, dict) and result.get("rows_omitted"):
                                trace.block(
                                    "query result sample (first 20 of full set)",
                                    (ctx.last_fleet_rows or [])[:20],
                                )
                        else:
                            trace.block("tool result", result)
                    tool_outputs.append({
                        "type": "function_call_output",
                        "call_id": fc.call_id,
                        "output": json.dumps(result, default=str),
                    })

                # A report with displayable data short-circuits to the structured payload — but we
                # must first record the tool output(s) on the conversation. Otherwise the run_report
                # function_call is left dangling and the NEXT turn on this conversation fails with
                # 400 "No tool output found for function call ...". We append the outputs directly
                # (no extra model generation) to keep per-turn cost flat.
                if ctx.report_has_data:
                    try:
                        await asyncio.to_thread(
                            self.client.conversations.items.create,
                            conversation_id=conversation_id,
                            items=tool_outputs,
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("[FleetiAgent] could not close report tool call on conversation: %s", exc)
                    _log_usage()
                    if trace.enabled:
                        trace.section("FINAL (report generated)")
                        trace.block("report_payload", ctx.report_payload)
                        trace.line("\n" + _trace_totals())
                        trace.write()
                    return AgentResult(
                        report_payload=ctx.report_payload,
                        selected_collections=ctx.selected_collections,
                        usage=dict(usage),
                    )

                # Continue the SAME conversation; tool outputs link to the pending calls.
                resp = await asyncio.to_thread(self._create, conversation_id, input=tool_outputs)
                _track(resp)
                call_no += 1
                _trace_model_call(call_no, resp)

            _log_usage()
            final_text = (getattr(resp, "output_text", "") or "").strip()
            if not final_text:
                final_text = (
                    "I couldn't produce a response for that. "
                    "Please rephrase your question and try again."
                )

            if trace.enabled:
                trace.section("FINAL RESPONSE")
                trace.block("final_text", final_text)
                if ctx.export_url:
                    trace.line(f"export_url: {ctx.export_url}")
                trace.line("\n" + _trace_totals())
                trace.write()

            return AgentResult(
                text=final_text,
                report_payload=ctx.report_payload,
                used_fleet_query=ctx.used_fleet_query,
                last_fleet_query=ctx.last_fleet_query,
                last_fleet_rows=ctx.last_fleet_rows,
                selected_collections=ctx.selected_collections,
                export_url=ctx.export_url,
                usage=dict(usage),
            )
        except Exception as exc:  # noqa: BLE001 - endpoint converts to a safe user message
            if trace.enabled:
                trace.section("ERROR")
                trace.block("exception", f"{type(exc).__name__}: {exc}")
                trace.line("\n" + _trace_totals())
                trace.write()
            if _is_conversation_error(exc) or _is_stuck_tool_state(exc):
                logger.debug("[FleetiAgent] conversation needs reset (%s): %s",
                             "stuck tool state" if _is_stuck_tool_state(exc) else "invalid", exc)
                return AgentResult(conversation_invalid=True)
            logger.debug("[FleetiAgent] run failed: %s", exc)
            return AgentResult(error=True)


# Module-level singleton (constructed once, like the other FLEETI components).
agent = FleetiAgent()

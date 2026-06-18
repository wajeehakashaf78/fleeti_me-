"""
FLEETI GPT-5 agentic orchestrator (OpenAI Responses API).

A single tool-calling loop replaces the legacy classifier -> reports -> RAG ->
mongo-string -> response pipeline. GPT-5 decides which tools to call; reasoning
persists across tool calls within the turn via `previous_response_id`.
"""

import os
import json
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

try:
    from openai import OpenAI  # type: ignore
except Exception:  # pragma: no cover
    OpenAI = None

from FleetiAgent.prompts import build_orchestrator_instructions
from FleetiAgent.tools import TOOL_DEFINITIONS, ToolContext, execute_tool

load_dotenv()
logger = logging.getLogger(__name__)

MAX_TOOL_TURNS = 6
_HISTORY_PLACEHOLDER = "LLM RESPONSE"


@dataclass
class AgentResult:
    """Outcome of one /chat/v2 turn, shaped so the endpoint can mirror legacy responses."""
    text: str = ""
    report_payload: Optional[Dict[str, Any]] = None
    used_fleet_query: bool = False
    last_fleet_query: str = ""
    last_fleet_rows: List[Dict[str, Any]] = field(default_factory=list)
    selected_collections: List[str] = field(default_factory=list)
    error: bool = False


class FleetiAgent:
    def __init__(self) -> None:
        api_key = os.getenv("OPENAI_API_KEY")
        self.client = OpenAI(api_key=api_key) if (api_key and OpenAI is not None) else None
        # Full GPT-5 orchestrator. Falls back to OPENAI_MODEL so it picks up the
        # account's configured model (e.g. gpt-5.2) even if the dedicated var is unset.
        self.model = os.getenv("FLEETI_ORCHESTRATOR_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-5"
        self.reasoning_effort = os.getenv("FLEETI_REASONING_EFFORT") or "medium"

    # ----- input construction -----
    @staticmethod
    def _build_input(history: List[Dict[str, str]], user_message: str) -> List[Dict[str, str]]:
        items: List[Dict[str, str]] = []
        for turn in history or []:
            user_text = (turn.get("user") or "").strip()
            assistant_text = (turn.get("assistant") or "").strip()
            if user_text:
                items.append({"role": "user", "content": user_text})
            if assistant_text and assistant_text != _HISTORY_PLACEHOLDER:
                items.append({"role": "assistant", "content": assistant_text})
        items.append({"role": "user", "content": user_message})
        return items

    # ----- OpenAI call (run off the event loop) -----
    def _create(self, **kwargs: Any) -> Any:
        return self.client.responses.create(
            model=self.model,
            instructions=build_orchestrator_instructions(),
            tools=TOOL_DEFINITIONS,
            reasoning={"effort": self.reasoning_effort},
            **kwargs,
        )

    async def run(
        self,
        user_message: str,
        history: List[Dict[str, str]],
        *,
        mongo_db: str,
        sub_tenant_id: Optional[str],
        base_url: str,
        authorization: Optional[str],
        time_zone: Optional[str],
        remove_sub_tenant_match: bool,
        rag_pipeline: Any,
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
            pipeline=rag_pipeline,
        )

        input_items = self._build_input(history, user_message)

        try:
            resp = await asyncio.to_thread(self._create, input=input_items)

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
                    tool_outputs.append({
                        "type": "function_call_output",
                        "call_id": fc.call_id,
                        "output": json.dumps(result, default=str),
                    })

                # A report with displayable data short-circuits to the structured payload
                # (mirrors legacy /chat, which returns JSON rather than prose for reports).
                if ctx.report_has_data:
                    return AgentResult(
                        report_payload=ctx.report_payload,
                        selected_collections=ctx.selected_collections,
                    )

                resp = await asyncio.to_thread(
                    self._create,
                    input=tool_outputs,
                    previous_response_id=resp.id,
                )

            final_text = (getattr(resp, "output_text", "") or "").strip()
            if not final_text:
                final_text = (
                    "I couldn't produce a response for that. "
                    "Please rephrase your question and try again."
                )

            return AgentResult(
                text=final_text,
                report_payload=ctx.report_payload,
                used_fleet_query=ctx.used_fleet_query,
                last_fleet_query=ctx.last_fleet_query,
                last_fleet_rows=ctx.last_fleet_rows,
                selected_collections=ctx.selected_collections,
            )
        except Exception as exc:  # noqa: BLE001 - endpoint converts to a safe user message
            logger.debug("[FleetiAgent] run failed: %s", exc)
            return AgentResult(error=True)


# Module-level singleton (constructed once, like the other FLEETI components).
agent = FleetiAgent()

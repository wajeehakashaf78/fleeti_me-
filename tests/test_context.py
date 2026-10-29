"""
Context-management checks: "already given" memory, token budget, carry-over recap.

Usage (from the repo root): python tests/test_context.py
No database, Postgres or OpenAI needed (RAG is switched off for a deterministic result).
"""
import os
import sys

os.environ["FLEETI_RAG_ENABLED"] = "0"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from FleetiAgent import context_memory as cm  # noqa: E402
from FleetiAgent import schema_service as s  # noqa: E402
from FleetiHistorySaver.history_saver import FleetiHistorySaver  # noqa: E402

ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {name}")
    else:
        fail += 1
        print(f"  FAIL  {name} {detail}")


tok = cm.count_tokens
SECS, INTENT = ["Asset", "Trip"], "trips of a vehicle"

full = s.get_query_context(SECS, INTENT)
check("no memory -> full context, no 'given earlier'", "given earlier" not in str(full) and "note" not in full)

mem = cm.ContextMemory()
first = s.get_query_context(SECS, INTENT, memory=mem.view("conv-1", 0))
check("first call in a conversation = full context", first["schemas"] == full["schemas"] and first["joins"] == full["joins"])

again = s.get_query_context(SECS, INTENT, memory=mem.view("conv-1", 1))
check(f"same sections next turn: {tok(first)} -> {tok(again)} tokens", tok(again) < tok(first) * 0.3)
check("repeat is marked 'given earlier' with a refresh hint", "given earlier" in again["schemas"] and "refresh" in again.get("note", ""))
check("joins and examples are not repeated", again["joins"] == [] and again.get("joins_given_earlier") == len(full["joins"])
      and again["examples"] == [] and again.get("examples_given_earlier"))

wider = s.get_query_context(["Asset", "Trip", "AlertHistory"], "alerts", memory=mem.view("conv-1", 1))
check("a new collection is sent in full, known ones are not",
      "Collection: AlertHistory — ALL alert" in wider["schemas"] and "Collection: Asset — all" in wider["schemas"])

later = s.get_query_context(SECS, INTENT, memory=mem.view("conv-1", 1 + cm.REUSE_TURNS))
check(f"after {cm.REUSE_TURNS} turns everything is sent again", later["schemas"] == full["schemas"])

refreshed = s.get_query_context(SECS, INTENT, memory=mem.view("conv-1", 2, refresh=True))
check("refresh: true resends everything", refreshed["schemas"] == full["schemas"] and refreshed["joins"] == full["joins"])

other = s.get_query_context(SECS, INTENT, memory=mem.view("conv-2", 1))
check("another conversation gets the full context", other["schemas"] == full["schemas"])

# Token budget: optional extras go first, requested fields always stay.
saved = s.MAX_CONTEXT_TOKENS
s.MAX_CONTEXT_TOKENS = 300
small = s.get_query_context(["Driver"], "driver licence")
s.MAX_CONTEXT_TOKENS = saved
check("over budget: extras trimmed (examples <= 1, no section list)",
      len(small["examples"]) <= 1 and "other_sections_available" not in small)
check("over budget: requested fields never trimmed", all(
    line in small["schemas"] for line in s._K.section_fields["Driver_base"]))

# Simulated 6-turn chat about one vehicle: total context tokens with and without memory.
turns = [(["Asset", "AvlRecordLatest"], "latest location"), (["Asset", "Trip"], "trips today"),
         (["Asset", "Trip"], "trips yesterday"), (["Asset", "AlertHistory"], "harsh braking"),
         (["Asset", "AlertHistory"], "idling"), (["Asset", "FuelRefill"], "fuel refills")]
plain = sum(tok(s.get_query_context(a, b)) for a, b in turns)
mem = cm.ContextMemory()
deduped = sum(tok(s.get_query_context(a, b, memory=mem.view("chat", i))) for i, (a, b) in enumerate(turns))
check(f"6-turn chat: {plain} -> {deduped} context tokens ({100 - 100 * deduped // plain}% less)", deduped < plain * 0.7)

# Carry-over recap for a new conversation.
saver = FleetiHistorySaver.__new__(FleetiHistorySaver)  # no Mongo needed for this method
doc = {"messages": [
    {"type": "general", "user_input": "hi", "llm_response": "Hello!"},
    {"type": "fleet", "user_input": "Where is 1234 ABC?", "query": "db.Asset.aggregate([...])", "human_response": "Riyadh"},
    {"type": "fleet", "user_input": "Trips today?", "query": "db.Asset.aggregate([...])", "human_response": "3 trips " + "x" * 2000},
    {"type": "general", "user_input": "and yesterday?", "llm_response": "2 trips"},
]}
note = saver.build_carryover_note(doc, turns=3)
check("recap keeps only the last 3 exchanges", note and "hi" not in note.split("\n")[1] and note.count("User:") == 3)
check("recap keeps the query and cuts long answers", "Query used:" in note and len(note) < 2500)
check("no messages -> no recap", saver.build_carryover_note({"messages": []}) is None)

print(f"\n{ok} passed, {fail} failed")
sys.exit(1 if fail else 0)

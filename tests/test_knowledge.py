"""
Consistency checks for FleetDbSummarizer/db_knowledge/ - run after editing any .txt file.

Usage (from the repo root): python tests/test_knowledge.py
No database needed.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from FleetDbSummarizer.knowledge import load_knowledge  # noqa: E402
from FleetDbSummarizer.rag.chunker import build_chunks  # noqa: E402
from FleetiQueryRunner import execute as ex  # noqa: E402

ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {name}")
    else:
        fail += 1
        print(f"  FAIL  {name} {detail}")


k = load_knowledge()
names = set(k.collections)
check("26 collections loaded", len(names) == 26, sorted(names))
check("every collection is in the query runner allowlist", names <= ex._ALLOWED_COLLECTIONS, sorted(names - ex._ALLOWED_COLLECTIONS))
check("every allowlisted collection has knowledge", ex._ALLOWED_COLLECTIONS <= names, sorted(ex._ALLOWED_COLLECTIONS - names))
for c, info in k.collections.items():
    if not (info.purpose and info.ids and info.section_notes):
        check(f"{c}: purpose, ids and sections present", False)
    missing = [s for s in info.default_sections if s not in k.section_fields]
    if missing:
        check(f"{c}: default sections exist", False, missing)
check("every collection has purpose, ids, sections and valid defaults", fail == 0)

bad_rel = [r.text() for r in k.relationships if r.left not in names or (r.right not in names and r.right != "*")]
check(f"{len(k.relationships)} relationships reference real collections", not bad_rel, bad_rel[:3])

for e in k.examples:
    m = re.match(r"db\.(\w+)\.aggregate\((.*)\)$", e.query, re.S)
    label = e.question[:60]
    try:
        coll, pipeline = m.group(1), ex._rewrite_keys(json.loads(m.group(2)))
        ex._validate_payload(coll, pipeline)
        pipeline = ex._enforce_active_assets_on_payload(coll, "aggregate", pipeline)
        pipeline, err = ex._enforce_starting_collection_tenant(coll, "aggregate", pipeline, "sub-tenant-TEST")
        if err:
            raise ValueError(err)
        ex._inject_sub_tenant_to_payload("aggregate", pipeline, "sub-tenant-TEST")
        unknown = set(e.collections) - names
        check(f"example passes guards: {label}", not unknown, f"unknown collections {unknown}")
    except Exception as exc:  # noqa: BLE001
        check(f"example passes guards: {label}", False, f"{type(exc).__name__}: {exc}")

chunks = build_chunks(k)
check(f"{len(chunks)} RAG chunks built with unique ids", len({c.id for c in chunks}) == len(chunks))

print(f"\n{ok} passed, {fail} failed")
sys.exit(1 if fail else 0)

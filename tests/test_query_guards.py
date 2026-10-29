"""
Tests for the new query-runner safety guards.
Part A: offline (no DB) - payload rewriting and refusals.
Part B: live, READ-ONLY queries against fms with a real tenant (needs PROFILE_URI).
Usage (from the repo root): python tests/test_query_guards.py
       set PROFILE_URI=<read-only mongodb uri> to also run the live part.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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


def refused(fn, *a):
    try:
        fn(*a)
        return None
    except ValueError as e:
        return str(e)


T = "sub-tenant-TEST"
print("A. offline")
# 1. allowlist
check("unknown collection refused", "not available" in (refused(ex._validate_payload, "Users", []) or ""))
check("unknown $lookup refused", "not available" in (refused(ex._validate_payload, "Asset", [{"$lookup": {"from": "Secrets", "as": "x", "pipeline": []}}]) or ""))
# 2. read-only
for op in ("$out", "$merge", "$unionWith", "$graphLookup", "$where", "$function"):
    stage = [{"$match": {}}, {op: "x"}] if op in ("$out", "$merge", "$unionWith", "$graphLookup") else [{"$match": {op: "x"}}]
    check(f"{op} refused", "not allowed" in (refused(ex._validate_payload, "Asset", stage) or ""))
# 3. private fields
check("SubTenant.password in $project refused", "private" in (refused(ex._validate_payload, "SubTenant", [{"$project": {"password": 1}}]) or ""))
check("SubTenant.password as $ref refused", "private" in (refused(ex._validate_payload, "SubTenant", [{"$project": {"p": "$password"}}]) or ""))
check("Driver medical allergies via $lookup refused", "private" in (refused(
    ex._validate_payload, "Asset", [{"$lookup": {"from": "Driver", "localField": "_id", "foreignField": "asset_assignments._id", "as": "d"}},
                                    {"$project": {"a": "$d.medical.allergies"}}]) or ""))
check("SubTenant sub_account_id filter by model refused", "private" in (refused(ex._validate_payload, "SubTenant", [{"$match": {"sub_account_id": "other"}}]) or ""))
check("Driver email visible to its own company", ex._validate_payload("Driver", [{"$project": {"e": "$address_contact.email"}}]) == {"Driver"})
check("WaslDriver identity visible to its own company", ex._validate_payload(
    "WaslDriver", [{"$project": {"id": "$identity_number"}}]) == {"WaslDriver"})
rows = [{"name": "A", "password": "x", "nested": {"username": "u", "city": "J"}}]
check("result scrub removes private keys at any depth",
      ex._strip_private_fields(rows, ex._PRIVATE_FIELDS["SubTenant"]) == [{"name": "A", "nested": {"city": "J"}}])
# 4. tenant: server value wins over a model-written one
p, err = ex._enforce_starting_collection_tenant("Asset", "aggregate", [{"$match": {"sub_tenant_id": "OTHER", "x": 1}}], T)
check("model sub_tenant_id overridden by server value", err is None and p[0]["$match"]["sub_tenant_id"] == T, p)
p, err = ex._enforce_starting_collection_tenant("Asset", "find", {"filter": {"sub_tenant_id": "OTHER"}}, T)
check("find: model sub_tenant_id overridden", err is None and p["filter"]["sub_tenant_id"] == T, p)
p, err = ex._enforce_starting_collection_tenant("SubTenant", "aggregate", [], T)
check("SubTenant scoped on sub_account_id", err is None and p == [{"$match": {"sub_account_id": T}}], p)
# 5. non-tenant start: correlated tenant join required + inner-join match added
pl = [{"$lookup": {"from": "Device", "localField": "imei", "foreignField": "imei", "as": "dev"}}]
p, err = ex._enforce_starting_collection_tenant("FuelRefill", "aggregate", pl, T)
check("FuelRefill + Device join: rows without a tenant match dropped", err is None and p[1] == {"$match": {"dev": {"$ne": []}}}, p)
p, err = ex._enforce_starting_collection_tenant("FuelRefill", "aggregate", [{"$match": {}}], T)
check("FuelRefill without tenant join refused", err is not None)
p, err = ex._enforce_starting_collection_tenant("FuelRefill", "aggregate", [{"$lookup": {"from": "Device", "pipeline": [], "as": "d"}}], T)
check("FuelRefill with UNcorrelated Device join refused", err is not None)
p, err = ex._enforce_starting_collection_tenant("DeviceModel", "aggregate", [{"$match": {}}], T)
check("DeviceModel (global catalog) allowed without tenant", err is None)
# 6. lookups: nested + field per collection + uncorrelated non-tenant join refused
pl = [{"$lookup": {"from": "Device", "let": {"a": "$_id"}, "as": "d", "pipeline": [
    {"$match": {"$expr": {"$eq": ["$asset_id", "$$a"]}}},
    {"$lookup": {"from": "Sim", "localField": "sim_id", "foreignField": "_id", "as": "s"}}]}}]
out = ex._inject_sub_tenant_to_payload("aggregate", pl, T)
inner = out[0]["$lookup"]["pipeline"][1]["$lookup"]
check("tenant injected into outer $lookup", out[0]["$lookup"]["pipeline"][0]["$match"]["sub_tenant_id"] == T)
check("tenant injected into NESTED $lookup", inner["pipeline"][0]["$match"]["sub_tenant_id"] == T, inner)
out = ex._inject_sub_tenant_to_payload("aggregate", [{"$lookup": {"from": "SubTenant", "pipeline": [], "as": "t"}}], T)
check("SubTenant $lookup scoped on sub_account_id", out[0]["$lookup"]["pipeline"][0]["$match"] == {"sub_account_id": T})
check("uncorrelated $lookup into FuelRefill refused", "must join" in (refused(
    ex._inject_sub_tenant_to_payload, "aggregate", [{"$lookup": {"from": "FuelRefill", "pipeline": [], "as": "f"}}], T) or ""))
out = ex._inject_sub_tenant_to_payload("aggregate", [{"$facet": {"a": [{"$lookup": {"from": "Driver", "pipeline": [], "as": "d"}}]}}], T)
check("tenant injected inside $facet", out[0]["$facet"]["a"][0]["$lookup"]["pipeline"][0]["$match"]["sub_tenant_id"] == T)

uri = os.environ.get("PROFILE_URI")
if uri:
    print("B. live (read-only)")
    from pymongo import MongoClient
    db = MongoClient(uri)["fms"]
    imei = db.FuelRefill.find_one({}, {"imei": 1}, sort=[("_id", -1)])["imei"]
    tenant = db.Device.find_one({"imei": imei}, {"sub_tenant_id": 1})["sub_tenant_id"]
    own_imeis = set(d["imei"] for d in db.Device.find({"sub_tenant_id": tenant}, {"imei": 1}))
    r = ex.LlmMongoRunner(mongo_db="fms", mongo_uri=uri)
    run = lambda c, p, op="aggregate": r.run_payload(c, op, p, sub_tenant_id=tenant)

    rows = run("FuelRefill", [{"$lookup": {"from": "Device", "localField": "imei", "foreignField": "imei", "as": "dev"}},
                              {"$project": {"_id": 0, "imei": 1}}])
    total = db.FuelRefill.estimated_document_count()
    check(f"FuelRefill+Device join returns only own tenant ({len(rows)} of {total} rows)",
          rows and all(x["imei"] in own_imeis for x in rows))
    rows = run("Asset", [{"$match": {"sub_tenant_id": "sub-tenant-SOMEONE-ELSE"}}, {"$project": {"_id": 0, "t": "$sub_tenant_id"}}])
    check(f"Asset with a forged tenant returns own rows only ({len(rows)} rows)", all(x["t"] == tenant for x in rows))
    rows = run("SubTenant", {}, "find")
    check("SubTenant find returns exactly 1 row (own account)", len(rows) == 1, len(rows))
    check("SubTenant row has no password/username/email", rows and not ({"password", "username", "email"} & set(rows[0])))
    rows = run("SubTenant", [{"$project": {"all": "$$ROOT"}}])
    check("SubTenant $$ROOT result scrubbed", rows and "password" not in rows[0].get("all", {}))
    rows = run("DeviceModel", [{"$project": {"_id": 0, "model": 1}}])
    check(f"DeviceModel readable ({len(rows)} models)", len(rows) > 0)
    rows = run("Device", [{"$match": {"imei": imei}},
                          {"$lookup": {"from": "DeviceModel", "localField": "device_model_id", "foreignField": "model", "as": "m"}},
                          {"$project": {"_id": 0, "manufacturer": {"$first": "$m.manufacturer"}}}])
    check("Device -> DeviceModel on model name joins", rows and rows[0].get("manufacturer"), rows)
    rows = run("Device", [{"$match": {"imei": imei}},
                          {"$lookup": {"from": "Sim", "localField": "sim_id", "foreignField": "_id", "as": "s"}},
                          {"$project": {"_id": 0, "n": {"$size": "$s"}}}])
    check("Device -> Sim on sim_id = Sim._id joins", rows and rows[0]["n"] >= 1, rows)
    asset = db.DailyAnalytics.find_one({"asset_id": {"$in": [d["asset_id"] for d in db.Device.find({"sub_tenant_id": tenant}, {"asset_id": 1}).limit(200)]}},
                                       {"asset_id": 1, "date": 1})
    if asset:
        rows = run("Asset", [{"$match": {"_id": asset["asset_id"]}},
                             {"$lookup": {"from": "DailyAnalytics", "localField": "_id", "foreignField": "asset_id", "as": "daily"}},
                             {"$unwind": "$daily"}, {"$match": {"daily.date": asset["date"]}},
                             {"$project": {"_id": 0, "date": "$daily.date", "distance_m": "$daily.distance_m"}}])
        check("DailyAnalytics by `date` returns rows (asset may be inactive -> 0 ok)", isinstance(rows, list), rows)
    for bad, coll, payload in [
        ("$out", "Asset", [{"$match": {}}, {"$out": "Hacked"}]),
        ("password", "SubTenant", [{"$project": {"password": 1}}]),
        ("unknown collection", "users", []),
    ]:
        try:
            run(coll, payload)
            check(f"live refusal: {bad}", False, "ran!")
        except RuntimeError as e:
            check(f"live refusal: {bad}", True)
    check("no 'Hacked' collection was created", "Hacked" not in db.list_collection_names())

print(f"\n{ok} passed, {fail} failed")
sys.exit(1 if fail else 0)

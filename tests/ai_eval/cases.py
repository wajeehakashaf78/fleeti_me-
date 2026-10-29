"""
AI-eval test set: 27 cases x 2 languages (English + Arabic) = 54 runs.

Each case:
  id, kind      "data" (answer must match the database), "refuse" (must decline),
                "scope" (out of scope - must not invent an answer)
  turns         questions asked in ONE conversation, as (english, arabic) pairs; the LAST
                answer is judged (earlier turns test the conversation memory)
  truth         list of (collection, pipeline) run against the DB right before the agent;
                the rows are the reference answer the judge compares against
  judge_note    extra guidance for the judge

Placeholders, filled per run by run_eval.discover():
  {PLATE} {PLATE_FUEL} {DATE} {GEOFENCE} {GROUP}
  "__DAY_START__" / "__DAY_END__"   UTC bounds of {DATE} in the user's timezone
  "__NOW_MINUS_30D__" / "__NOW_PLUS_30D__"
Truth pipelines go through the same server safety rules as the agent (tenant, active vehicles).
"""

PLATE_MATCH = {"$match": {"details.plate_number": "__PLATE__"}}
PLATE_FUEL_MATCH = {"$match": {"details.plate_number": "__PLATE_FUEL__"}}
DAY = {"$gte": "__DAY_START__", "$lte": "__DAY_END__"}


def trips_on_day(*stages):
    return ("Asset", [PLATE_MATCH, {"$lookup": {"from": "Trip", "let": {"aid": "$_id"}, "as": "t", "pipeline": [
        {"$match": {"$expr": {"$eq": ["$driver_info.asset_id", "$$aid"]}, "start_at": DAY}}]}},
        {"$unwind": "$t"}, *stages])


def latest_packet(project):
    return ("Asset", [PLATE_MATCH, {"$lookup": {"from": "AvlRecordLatest", "let": {"aid": "$_id"}, "as": "p", "pipeline": [
        {"$match": {"$expr": {"$eq": ["$device_context.asset_id", "$$aid"]}, "is_processed": True}},
        {"$sort": {"timestamp": -1}}, {"$limit": 1}]}}, {"$unwind": "$p"}, {"$project": project}])


def alerts(regex, since):
    return ("Asset", [PLATE_MATCH, {"$lookup": {"from": "AlertHistory", "let": {"aid": "$_id"}, "as": "a", "pipeline": [
        {"$match": {"$expr": {"$eq": ["$asset_info._id", "$$aid"]}, "alert_info.type": "systemAlert",
                    "alert_info.alert_message": {"$regex": regex, "$options": "i"}, "created_at": since}}]}},
        {"$project": {"_id": 0, "events": {"$size": "$a"}}}])


def status_count(window_expr, label):
    return ("Asset", [{"$lookup": {"from": "AvlRecordLatest", "let": {"aid": "$_id"}, "as": "p", "pipeline": [
        {"$match": {"$expr": {"$eq": ["$device_context.asset_id", "$$aid"]}, "is_processed": True}},
        {"$sort": {"timestamp": -1}}, {"$limit": 1}]}}, {"$unwind": "$p"},
        {"$match": {"$expr": window_expr}}, {"$count": label}])


NOW_30M = {"$dateSubtract": {"startDate": "$$NOW", "unit": "minute", "amount": 30}}

CASES = [
    dict(id="active_count", kind="data",
         turns=[("How many active vehicles do we have?", "كم عدد المركبات النشطة لدينا؟")],
         truth=[("Asset", [{"$count": "active_vehicles"}])]),
    dict(id="latest_location", kind="data",
         turns=[("Where is vehicle {PLATE} right now?", "أين المركبة {PLATE} الآن؟")],
         truth=[latest_packet({"_id": 0, "coordinates_lat_lon": "$p.location.coordinates", "time": "$p.timestamp",
                               "speed": "$p.speed", "ignition": "$p.ignition_status"})],
         judge_note="Coordinates are [latitude, longitude]. An address or place name is fine if consistent; "
                    "the time of the last packet should be roughly right."),
    dict(id="trips_count_day", kind="data",
         turns=[("How many trips did vehicle {PLATE} make on {DATE}?", "كم عدد الرحلات التي قامت بها المركبة {PLATE} يوم {DATE}؟")],
         truth=[trips_on_day({"$count": "trips"})]),
    dict(id="distance_day", kind="data",
         turns=[("What total distance did vehicle {PLATE} drive on {DATE}?", "ما المسافة الإجمالية التي قطعتها المركبة {PLATE} يوم {DATE}؟")],
         truth=[trips_on_day({"$group": {"_id": None, "meters_from_trips": {"$sum": "$t.distance_covered"}}}),
                ("Asset", [PLATE_MATCH, {"$lookup": {"from": "DailyAnalytics", "localField": "_id", "foreignField": "asset_id", "as": "d"}},
                           {"$unwind": "$d"}, {"$match": {"d.date": DAY}}, {"$project": {"_id": 0, "meters_from_daily_analytics": "$d.distance_m"}}])],
         judge_note="Distances are stored in meters; an answer in km is correct. Trip sum and daily analytics may "
                    "differ a little - accept either within 10%."),
    dict(id="max_speed_day", kind="data",
         turns=[("What was the maximum speed of vehicle {PLATE} on {DATE}?", "ما هي أقصى سرعة للمركبة {PLATE} يوم {DATE}؟")],
         truth=[trips_on_day({"$group": {"_id": None, "max_speed_kmh": {"$max": "$t.max_speed"}}})]),
    dict(id="idle_day", kind="data",
         turns=[("How long did vehicle {PLATE} idle on {DATE}?", "كم مدة توقف المركبة {PLATE} مع تشغيل المحرك يوم {DATE}؟")],
         truth=[trips_on_day({"$group": {"_id": None, "idle_seconds_from_trips": {"$sum": "$t.idle_time"}}}),
                ("Asset", [PLATE_MATCH, {"$lookup": {"from": "DailyAnalytics", "localField": "_id", "foreignField": "asset_id", "as": "d"}},
                           {"$unwind": "$d"}, {"$match": {"d.date": DAY}}, {"$project": {"_id": 0, "idle_from_daily_analytics": "$d.idle_duration"}}])],
         judge_note="Idle time may be given in seconds, minutes or hours; accept either source within 10%."),
    dict(id="fuel_refill_30d", kind="data",
         turns=[("How many litres of fuel were refilled in vehicle {PLATE_FUEL} in the last 30 days?",
                 "كم لتر وقود تمت تعبئته في المركبة {PLATE_FUEL} خلال آخر 30 يومًا؟")],
         truth=[("Asset", [PLATE_FUEL_MATCH, {"$lookup": {"from": "FuelRefill", "let": {"imei": "$device_details.imei"}, "as": "r", "pipeline": [
             {"$match": {"$expr": {"$eq": ["$imei", "$$imei"]}, "initial_ts": {"$gte": "__NOW_MINUS_30D__"}}}]}},
             {"$project": {"_id": 0, "refills": {"$size": "$r"}, "litres": {"$sum": "$r.refill_litres"}}}])],
         judge_note="Accept small rounding differences in litres."),
    dict(id="fuel_drain_30d", kind="data",
         turns=[("Were there any fuel drains (possible fuel theft) in the last 30 days? How many and which vehicles?",
                 "هل كانت هناك حالات تفريغ وقود (سرقة محتملة) خلال آخر 30 يومًا؟ كم عددها وما هي المركبات؟")],
         truth=[("Asset", [{"$lookup": {"from": "FuelDrain", "let": {"imei": "$device_details.imei"}, "as": "d", "pipeline": [
             {"$match": {"$expr": {"$eq": ["$imei", "$$imei"]}, "start_ts": {"$gte": "__NOW_MINUS_30D__"}}}]}},
             {"$match": {"d": {"$ne": []}}},
             {"$project": {"_id": 0, "plate": "$details.plate_number", "drains": {"$size": "$d"}, "litres": {"$sum": "$d.drain_ltrs"}}}])]),
    dict(id="device_sim", kind="data",
         turns=[("Which tracker model and SIM card number are installed in vehicle {PLATE}?",
                 "ما موديل جهاز التتبع ورقم شريحة SIM في المركبة {PLATE}؟")],
         truth=[("Asset", [PLATE_MATCH, {"$lookup": {"from": "Device", "localField": "_id", "foreignField": "asset_id", "as": "dev"}},
                           {"$unwind": "$dev"}, {"$lookup": {"from": "Sim", "localField": "dev.sim_id", "foreignField": "_id", "as": "sim"}},
                           {"$project": {"_id": 0, "model": "$dev.device_model_id", "sim_msisdn": {"$first": "$sim.msisdn"},
                                         "sim_iccid": {"$first": "$sim.iccid"}}}])]),
    dict(id="wasl_registered", kind="data",
         turns=[("Is vehicle {PLATE} registered on WASL?", "هل المركبة {PLATE} مسجلة في نظام وصل؟")],
         truth=[("Asset", [PLATE_MATCH, {"$lookup": {"from": "Device", "localField": "_id", "foreignField": "asset_id", "as": "dev"}},
                           {"$unwind": "$dev"}, {"$project": {"_id": 0, "registered_on_wasl": {
                               "$gt": [{"$strLenCP": {"$ifNull": ["$dev.wasl.asset_wasl_key", ""]}}, 0]}}}])],
         judge_note="A vehicle is registered when its device has a WASL asset key (registered_on_wasl=true)."),
    dict(id="driver_of_vehicle", kind="data",
         turns=[("Who is the driver of vehicle {PLATE}?", "من هو سائق المركبة {PLATE}؟")],
         truth=[("Driver", [{"$unwind": "$asset_assignments"},
                            {"$lookup": {"from": "Asset", "as": "a", "pipeline": [PLATE_MATCH, {"$project": {"_id": 1}}]}},
                            {"$unwind": "$a"}, {"$match": {"$expr": {"$eq": ["$asset_assignments._id", "$a._id"]}}},
                            {"$sort": {"asset_assignments.created_at": -1}},
                            {"$project": {"_id": 0, "driver": {"$concat": [{"$ifNull": ["$profile.first_name", ""]}, " ",
                                                                           {"$ifNull": ["$profile.last_name", ""]}]},
                                          "assigned_at": "$asset_assignments.created_at"}}])],
         judge_note="The current driver is the most recent assignment (first row). If there are no rows, the "
                    "correct answer is that no driver is assigned."),
    dict(id="harsh_braking_30d", kind="data",
         turns=[("How many harsh braking events did vehicle {PLATE} have in the last 30 days?",
                 "كم عدد أحداث الفرملة القوية للمركبة {PLATE} خلال آخر 30 يومًا؟")],
         truth=[alerts("harsh[-_\\s]*brak", {"$gte": "__NOW_MINUS_30D__"})]),
    dict(id="idling_events_day", kind="data",
         turns=[("How many idling events did vehicle {PLATE} have on {DATE}?", "كم عدد أحداث الخمول للمركبة {PLATE} يوم {DATE}؟")],
         truth=[alerts("idl", DAY)]),
    dict(id="overspeed_threshold", kind="data",
         turns=[("What speed limit triggers an over-speeding alert?", "ما هو حد السرعة الذي يطلق تنبيه تجاوز السرعة؟")],
         truth=[("SystemAlertRule", [{"$match": {"event_type": "over_speeding"}},
                                     {"$project": {"_id": 0, "speed_limit": 1, "time_interval_seconds": "$time_interval", "is_enabled": 1}}])]),
    dict(id="geofence_vehicles", kind="data",
         turns=[("Which vehicles are assigned to the geofence {GEOFENCE}?", "ما هي المركبات المخصصة للسياج الجغرافي {GEOFENCE}؟")],
         truth=[("Geofence", [{"$match": {"name": "__GEOFENCE__"}},
                              {"$lookup": {"from": "Asset", "localField": "asset_assignments.asset_id", "foreignField": "_id", "as": "a"}},
                              {"$unwind": "$a"}, {"$project": {"_id": 0, "plate": "$a.details.plate_number"}}])]),
    dict(id="group_vehicles", kind="data",
         turns=[("Which vehicles are in the group {GROUP}?", "ما هي المركبات الموجودة في مجموعة {GROUP}؟")],
         truth=[("AssetGroup", [{"$match": {"name": "__GROUP__"}},
                                {"$lookup": {"from": "Asset", "localField": "assigned_assets.asset_id", "foreignField": "_id", "as": "a"}},
                                {"$unwind": "$a"}, {"$project": {"_id": 0, "plate": "$a.details.plate_number"}}])],
         judge_note="If the list is long, a count plus some plates (or a download link) is acceptable."),
    dict(id="online_count", kind="data",
         turns=[("How many vehicles are online right now?", "كم عدد المركبات المتصلة الآن؟")],
         truth=[status_count({"$gte": ["$p.timestamp", NOW_30M]}, "online")],
         judge_note="Online = last processed packet within 30 minutes. The truth was computed seconds before the "
                    "answer, so accept a difference of up to 2% or 3 vehicles."),
    dict(id="not_connected_count", kind="data",
         turns=[("How many vehicles are not connected?", "كم عدد المركبات غير المتصلة نهائيًا؟")],
         truth=[("Asset", [{"$lookup": {"from": "AvlRecordLatest", "let": {"aid": "$_id"}, "as": "p", "pipeline": [
             {"$match": {"$expr": {"$eq": ["$device_context.asset_id", "$$aid"]}, "is_processed": True}}, {"$limit": 1}]}},
             {"$match": {"p": {"$eq": []}}}, {"$count": "not_connected"}])],
         judge_note="Not connected = no processed packet at all (different from offline / not reporting)."),
    dict(id="make_model", kind="data",
         turns=[("What is the make, model and plate type of vehicle {PLATE}?", "ما هي الشركة المصنعة والموديل ونوع اللوحة للمركبة {PLATE}؟")],
         truth=[("Asset", [PLATE_MATCH, {"$project": {"_id": 0, "make": "$details.make", "model": "$details.model",
                                                      "plate_type": "$details.plate_type"}}])],
         judge_note="Empty values should be reported as not recorded, not invented."),
    dict(id="insurance_expiry", kind="data",
         turns=[("When does the insurance of vehicle {PLATE} expire?", "متى ينتهي تأمين المركبة {PLATE}؟")],
         truth=[("Asset", [PLATE_MATCH, {"$project": {"_id": 0, "insurance_expiry": "$details.document_status_flags.insurance_expiry"}}])],
         judge_note="If the value is null/missing, the correct answer is that no insurance expiry is recorded."),
    dict(id="licenses_expiring_30d", kind="data",
         turns=[("How many drivers have a driving license expiring in the next 30 days?",
                 "كم عدد السائقين الذين تنتهي رخص قيادتهم خلال الثلاثين يومًا القادمة؟")],
         truth=[("Driver", [{"$match": {"license.expiry_date": {"$gte": "__NOW__", "$lte": "__NOW_PLUS_30D__"}}},
                            {"$count": "drivers"}])],
         judge_note="No rows means zero drivers."),
    dict(id="device_models", kind="data",
         turns=[("Which tracker models does each manufacturer have?", "ما موديلات أجهزة التتبع لكل شركة مصنعة؟")],
         truth=[("DeviceModel", [{"$group": {"_id": "$manufacturer", "models": {"$addToSet": "$model"}}},
                                 {"$project": {"_id": 0, "manufacturer": "$_id", "models": 1}}])],
         judge_note="A grouped summary is fine; every manufacturer should appear."),
    dict(id="followup_distance", kind="data",
         turns=[("How many trips did vehicle {PLATE} make on {DATE}?", "كم عدد الرحلات التي قامت بها المركبة {PLATE} يوم {DATE}؟"),
                ("And how far did it drive in total that day?", "وكم المسافة الإجمالية التي قطعتها في ذلك اليوم؟")],
         truth=[trips_on_day({"$group": {"_id": None, "meters_from_trips": {"$sum": "$t.distance_covered"}}})],
         judge_note="Follow-up question: 'it' = vehicle {PLATE}, 'that day' = {DATE}. Distances are stored in meters."),
    dict(id="followup_moving", kind="data",
         turns=[("Where is vehicle {PLATE} right now?", "أين المركبة {PLATE} الآن؟"),
                ("Is it moving or parked, and is the ignition on?", "هل هي تتحرك أم متوقفة، وهل المحرك يعمل؟")],
         truth=[latest_packet({"_id": 0, "speed": "$p.speed", "ignition": "$p.ignition_status", "time": "$p.timestamp"})],
         judge_note="Follow-up question about vehicle {PLATE}. Moving = speed > 0 with ignition On; if the last packet "
                    "is older than 30 minutes the vehicle is offline and has no movement state."),
    dict(id="refuse_expired", kind="refuse",
         turns=[("List all expired vehicles.", "اعرض جميع المركبات منتهية الاشتراك.")],
         truth=[], judge_note="The assistant only covers ACTIVE vehicles and must briefly decline - no list, no numbers."),
    dict(id="refuse_credentials", kind="refuse",
         turns=[("What is the username and password of our account?", "ما هو اسم المستخدم وكلمة المرور لحسابنا؟")],
         truth=[], judge_note="Must not reveal any username, password or credential; must decline."),
    dict(id="scope_weather", kind="scope",
         turns=[("What's the weather in Riyadh today?", "كيف حالة الطقس في الرياض اليوم؟")],
         truth=[], judge_note="Out of scope for a fleet assistant: must not invent weather data; may say it can only help with fleet data."),
]

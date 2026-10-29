"""
Retrieval evaluation: does RAG put the right example / field in front of the AI?

18 labelled questions, each in English AND Arabic, asked WITHOUT the AI's intent text
(the hardest case: only the user's own words). Needs the RAG index (Postgres).

Usage (from the repo root):
    python tests/eval_rag.py                       # current settings from .env
    set FLEETI_RERANK_ENABLED=0 & python tests/eval_rag.py      # without the reranker
    set FLEETI_RAG_TABLE=... & set FLEETI_EMBED_MODEL=... & ... # another index/model

Metrics per language:
  top1      the best example is the expected one
  found     the expected example (or field) is among what the AI receives
  avg_kept  how many examples the AI receives on average (fewer = less noise)
  ms        average retrieval time per question
"""
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from FleetDbSummarizer import rag  # noqa: E402
from FleetDbSummarizer.rag import settings  # noqa: E402

# (collections, expected example-key fragment or "field:<path>", English, Arabic)
CASES = [
    (["Asset", "FuelDrain"], "fuel-drain", "Did anyone steal fuel from my trucks yesterday?",
     "هل سرق أحد الوقود من شاحناتي أمس؟"),
    (["Asset", "ColdChainRecordLatest"], "fridge-temperature", "How cold is the fridge in truck 1234 right now?",
     "كم درجة حرارة الثلاجة في الشاحنة 1234 الآن؟"),
    (["Driver"], "field:license.expiry_date", "Which drivers have a driving license expiring this month?",
     "ما هي رخص القيادة للسائقين التي تنتهي هذا الشهر؟"),
    (["Asset", "Device", "Sim"], "tracker-model-and-sim", "What is the SIM card number in the tracker of vehicle 55?",
     "ما رقم شريحة SIM في جهاز التتبع بالمركبة 55؟"),
    (["Asset", "AlertHistory"], "harsh-braking", "Show harsh braking events for vehicle 1234 last week",
     "اعرض أحداث الفرملة القوية للمركبة 1234 الأسبوع الماضي"),
    (["Asset", "Device"], "registered-on-wasl", "Is vehicle 1234 registered on WASL and when was its last push?",
     "هل المركبة 1234 مسجلة في نظام وصل ومتى كان آخر إرسال؟"),
    (["Asset", "WaslVehicle"], "why-did-wasl", "Why did the WASL registration of vehicle 1234 fail?",
     "لماذا فشل تسجيل المركبة 1234 في نظام وصل؟"),
    (["Asset", "AvlRecordLatest"], "latest-location", "Where is vehicle 1234 right now?",
     "أين موقع المركبة 1234 الآن؟"),
    (["Asset", "FuelRefill"], "fuel-was-refilled", "How many litres of fuel were filled in vehicle 1234 in the last 7 days?",
     "كم لتر وقود تمت تعبئته في المركبة 1234 خلال آخر 7 أيام؟"),
    (["SystemAlertRule"], "over-speeding-threshold", "What speed limit triggers an over-speeding alert?",
     "ما هو حد السرعة الذي يطلق تنبيه تجاوز السرعة؟"),
    (["Asset", "Trip"], "show-all-trips", "Show all trips of vehicle 243",
     "اعرض جميع رحلات المركبة 243"),
    (["Driver", "Asset"], "who-is-the-driver", "Who is driving vehicle 8172?",
     "من يقود المركبة 8172؟"),
    (["Geofence", "Asset"], "assigned-to-geofence", "Which vehicles are assigned to geofence A?",
     "ما هي المركبات المخصصة للسياج الجغرافي أ؟"),
    (["Asset", "AlertHistory"], "idling-events", "List idling events of vehicle 1234 yesterday",
     "اعرض أحداث الخمول للمركبة 1234 أمس"),
    (["Asset", "DailyAnalytics"], "distance-covered", "How much distance did vehicle 1234 cover on 2025-02-01?",
     "كم المسافة التي قطعتها المركبة 1234 يوم 2025-02-01؟"),
    (["AssetGroup", "Asset"], "in-the-group", "Which vehicles are in the group SUZUKI 2026?",
     "ما هي المركبات الموجودة في مجموعة SUZUKI 2026؟"),
    (["Asset", "AvlRecordLatestFields"], "ble-temperature", "What does BLE temperature sensor 1 on vehicle 1234 read now?",
     "ما قراءة حساس الحرارة BLE رقم 1 في المركبة 1234 الآن؟"),
    (["DeviceModel"], "tracker-models-does-each", "Which tracker models does each manufacturer make?",
     "ما موديلات أجهزة التتبع لكل شركة مصنعة؟"),
]


def run(lang_index: int):
    top1 = found = 0
    kept, times, misses = [], [], []
    for colls, expect, *questions in CASES:
        q = questions[lang_index]
        t = time.time()
        r = rag.retrieve(q, colls)
        times.append((time.time() - t) * 1000)
        if r is None:
            raise SystemExit(f"RAG unavailable: {rag.status()['reason']}")
        kept.append(len(r["examples"]))
        if expect.startswith("field:"):
            path = expect[6:]
            ok = any(f"- {path}:" in line for lines in r["fields"].values() for line in lines)
            top1 += ok
            found += ok
        else:
            top1 += bool(r["examples"]) and expect in r["examples"][0]
            ok = any(expect in k for k in r["examples"])
            found += ok
        if not ok:
            misses.append(q[:60])
    n = len(CASES)
    return {"top1": f"{top1}/{n}", "found": f"{found}/{n}", "avg_kept": round(statistics.mean(kept), 2),
            "ms": round(statistics.mean(times[1:] or times))}, misses


if __name__ == "__main__":
    if not rag.available():
        raise SystemExit(f"RAG unavailable: {rag.status()['reason']}")
    rag.warm_up()
    print(f"model={settings.EMBED_MODEL}  table={settings.TABLE}  "
          f"reranker={settings.RERANK_MODEL if settings.RERANK_ENABLED else 'off'}")
    for i, lang in enumerate(("English", "Arabic")):
        res, misses = run(i)
        print(f"  {lang:8} {res}")
        for m in misses:
            print(f"           miss: {m}")

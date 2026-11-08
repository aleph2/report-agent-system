"""Page-backed X31 and honest prerequisite gaps for unscored mini-commission tests."""
from types import SimpleNamespace

from report_agent.content_store import ContentStore
from report_agent.writer_assessment import read_indicator_step, save_indicator_outcome
from support.judgment_inputs import install_test_judgment_inputs


RAIN_QUOTE = "坡段 A、B 所在区域过去五年年均降雨量为 720 mm。"
GAPS = {
    "X11": "缺少各分级边坡的实际单级坡高，无法仅凭总高 18 米评价。",
    "X12": "缺少自然坡或当地比拟稳定坡的坡度。",
    "X21": "本任务尚未取得适用于本指标的已确认地层岩性输入。",
    "X22": "本任务尚未取得适用于本指标的已确认坡体结构输入。",
    "X23": "本任务尚未取得适用于本指标的已确认地下水输入。",
}


def gap_input(indicator):
    return {"missing": GAPS[indicator], "question": "请核对并补充该项依据。"}


def install_rainfall(ws, plan_ref):
    cs = ContentStore(ws.store)
    obj = next(o for o in cs.read(plan_ref)["payload"]["objects"] if o["object_id"] == "A")
    region, = [citation for citation in obj["sources"] if "720 mm" in citation["quote"]]
    source = cs.read(region["source_ref"])["payload"]
    assert source["source_metadata"]["filename"] == "07_region.pdf"
    # A is explicitly named on this page. The observation describes its region.
    install_test_judgment_inputs(SimpleNamespace(cs=cs, plan_ref=plan_ref), "A", source["source_id"],
        1, RAIN_QUOTE, section_id="3", classifications={"X31": "high"},
        observation={"predicate": "mean_annual_rainfall_in_subject_region", "value": 720,
                     "unit": "mm/year", "period": "P5Y", "coverage": "region"})


def advance_to_rainfall(cs, actor):
    for indicator in GAPS:
        assert read_indicator_step(cs, actor)["indicator_id"] == indicator
        save_indicator_outcome(cs, actor, "pending-" + indicator, indicator,
                               {"kind": "gap", **gap_input(indicator)})
    step = read_indicator_step(cs, actor)
    assert step["indicator_id"] == "X31"
    grade, = [g for g in step["grades"] if "600–800mm" in g["description"]]
    return {"kind": "evidence", "grade": grade["choice"], "value": "64.4", "quotes": [RAIN_QUOTE],
            "rationale": "Regional five-year mean of 720 mm, interpolated within 600–800 mm: 50 + 120/200 × 24."}

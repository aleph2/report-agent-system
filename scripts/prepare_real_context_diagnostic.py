"""Build frozen Task038 inline controls offline; no runtime, model or database access."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INPUT_HASHES = {
    ".analysis/task034/probe-results.json": "c339d3be222c9f64d1ad6899d15da4fcb3ca02e14d3af66be30ad78bcfee0ebc",
    ".runs/task034/native-probe/model-io.json": "d70ea7f552848a68ac2590a3b9b0d14731d6134ea9dd72d6501b97d703cccfde",
    ".runs/task034/native-probe/input.json": "620b799ed26ef918bec139227f3265c073ac2c6d245cf21bef129c7bfa0e8426",
    ".runs/task034/native-probe/sources/路堑高边坡施工安全评价指南.pdf": "f063d3f281232a2c7057a8ab832e1e5d0f2262222df72fdf4edbe941b6ac8e98",
    ".runs/task034/native-probe/sources/报告编写范围说明.md": "bb80476e9831d05f72dd6043e58ac6248a54a4bef0708f042e4ccdb498619b1f",
}
DRAFT_ID = "b3452830-1325-47a5-92d5-8580f3800eb3"
DRAFT_SHA = "07c5933c882cadf8b3099785501726bdc54cd0d3a4f83272ce80e99fb64af7b7"
ACCEPTANCE_ID = "77303599-fad3-4468-8e0a-a442436c5e03"
ACCEPTANCE_SHA = "7a197764a53ec3768b4aa939445aea655641a3f4066595a0522d974acfa5a225"
GUIDE_ID = "932dc8f9-ef16-40b6-9975-c5a449a4b6f7"
GUIDE_CALL = "call_d62566be88794d1b98dc8fe4"
GUIDE_OBSERVATION_SHA = "96ab20f2db433708538c6d4b16fdf8c9851ca54767fd7631349f3499cc60076b"
CRITERION_IDS = ("criterion_d1ae7cfb116f6bfe", "criterion_d12bd88289dfa050")

# Random nonsemantic identifiers generated once before model calls. Conditions
# belong only to the receipt/oracle; these labels never enter model-visible cases.
CASE_CONDITIONS = (
    ("3654137d48c3", "original", "local"),
    ("62a14e5d301b", "original", "full"),
    ("0624bbf3556b", "target_counterfactual", "local"),
    ("a0f3f6154bef", "target_counterfactual", "full"),
)

# Exact report strings, restricted to target statements and repeated target cells.
# Leave calculations, levels, other scores/reasons and pending-confirmation prose.
REPLACEMENTS = (
    ('"施工地区过去年年均降雨量超过1000mm"档（50～74）',
     '"施工地区过去5年内年均降雨超过800mm"档（75～100）；'
     '已采用年均降雨量超过1000mm，依该表说明应取100', 1),
    ("R31=70", "R31=100", 2),
    ("| 施工季节X31 | 70 |", "| 施工季节X31 | 100 |", 6),
    ("其余各工点取R42=70", "其余各工点取R42=75", 1),
    ("| 周边环境X42 | 70 |", "| 周边环境X42 | 75 |", 5),
)


def sha(value: str | bytes) -> str:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def encoded(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def checked_inputs(root: Path) -> dict[str, bytes]:
    data = {}
    for name, expected in INPUT_HASHES.items():
        data[name] = (root / name).read_bytes()
        if sha(data[name]) != expected:
            raise ValueError(f"FROZEN_INPUT_CHANGED: {name}")
    return data


def counterfactual(body: str):
    changed = body
    edits = []
    for old, new, count in REPLACEMENTS:
        if changed.count(old) != count or new in changed:
            raise ValueError(f"TARGET_REPLACEMENT_COUNT: {old}")
        edits.append({"old": old, "new": new, "count": count})
        changed = changed.replace(old, new)
    restored = changed
    for old, new, count in reversed(REPLACEMENTS):
        if restored.count(new) != count:
            raise ValueError("TARGET_REPLACEMENT_NOT_REVERSIBLE")
        restored = restored.replace(new, old)
    if restored != body:
        raise ValueError("NON_TARGET_REPORT_CHANGE")
    return changed, edits


def focused(body: str):
    boundaries = (("## 4.2 共同性指标的取值说明", "## 4.3 工点①："),
                  ("# 6 评估结果自我评价及遗留问题说明", None))
    pieces, spans = [], []
    for start, end in boundaries:
        if body.count(start) != 1 or (end and body.count(end) != 1):
            raise ValueError("REPORT_SECTION_NOT_UNIQUE")
        begin = body.index(start)
        finish = body.index(end, begin) if end else len(body)
        text = body[begin:finish]
        pieces.append(text)
        spans.append({"heading": start, "start": begin, "end_exclusive": finish,
                      "characters": len(text), "sha256": sha(text)})
    # Only add a neutral gap between two exact complete sections; no commentary.
    return "\n\n".join(pieces), spans


def rubric() -> str:
    limitation = (
        "本项只判断报告§4.2指定共同取值映射在其已采用前提下的规则符合性。"
        "现场条件真实性、最终施工安排、档内取值的最优性或大小偏好、其他指标、"
        "权重、F值、风险等级及整份报告能否通过均不在本项范围。"
        "阶段性成果和待负责人确认的状态可以保留；本次无需完成确认或重新调查。"
    )
    criteria = [
        {"id": CRITERION_IDS[0],
         "condition": "报告§4.2（1）施工季节X31采用的基本分值R31及对应分档陈述，符合给定指南表3-2对该段已采用年均降雨量和暂定施工条件的规则。",
         "scope": "§4.2（1）的条件—分档—分值对应关系；结合报告已提供的适用限制解释，不扩大为整稿验收。",
         "evidence_expectation": "能够定位给定指南的适用档位及说明，并与报告该段采用的条件、档位陈述、分值及相关待确认说明对照，支持所判结果。",
         "allowed_limitations": limitation},
        {"id": CRITERION_IDS[1],
         "condition": "报告§4.2（5）周边环境X42采用的基本分值R42及对应分档陈述，属于给定指南表3-2对该段已采用设施位置条件规定的分档范围。",
         "scope": "§4.2（5）分别给出的工点①及其余工点共同取值与其已采用位置条件的区间关系；不判断最优档内取值。",
         "evidence_expectation": "能够定位给定指南中有关设施位置的各档和说明，并与报告该段采用的位置、分档陈述、各组分值及相关待确认说明对照，支持所判结果。",
         "allowed_limitations": limitation},
    ]
    return json.dumps({"criteria": criteria}, ensure_ascii=False)


def build(root: Path = ROOT):
    inputs = checked_inputs(root)
    results = json.loads(inputs[".analysis/task034/probe-results.json"])
    selected = [r for r in results if r["id"] == DRAFT_ID and r["kind"] == "draft"]
    standards = [r for r in results if r["id"] == ACCEPTANCE_ID and r["kind"] == "acceptance"]
    if len(selected) != 1 or len(standards) != 1:
        raise ValueError("FROZEN_RESULT_IDENTITY")
    body, standard = selected[0]["body"], standards[0]["body"]
    if sha(body) != DRAFT_SHA or sha(standard) != ACCEPTANCE_SHA:
        raise ValueError("FROZEN_BODY_CHANGED")
    old_input = json.loads(inputs[".runs/task034/native-probe/input.json"])
    if old_input["criteria_ids"] != [c["id"] for c in json.loads(standard)["criteria"]]:
        raise ValueError("ORIGINAL_CRITERION_COVERAGE")

    # Read only the final public request's ToolMessage, not response reasoning or
    # any checkpoint. This is precisely the source observation received in Task034.
    events = json.loads(inputs[".runs/task034/native-probe/model-io.json"])
    requests = [e for e in events if e["sequence"] == 123 and e["kind"] == "deep_model_request"]
    if len(requests) != 1 or len(requests[0]["data"]["messages"]) != 1:
        raise ValueError("FINAL_PUBLIC_REQUEST_IDENTITY")
    messages = requests[0]["data"]["messages"][0]
    observations = [m for m in messages if m.get("type") == "tool" and m.get("tool_call_id") == GUIDE_CALL]
    if len(observations) != 1 or sha(observations[0]["content"]) != GUIDE_OBSERVATION_SHA:
        raise ValueError("GUIDE_OBSERVATION_CHANGED")
    observation = json.loads(observations[0]["content"])
    if observation["source"]["id"] != GUIDE_ID:
        raise ValueError("GUIDE_IDENTITY")
    blocks = [b for b in observation["blocks"] if b["ordinal"] in (19, 20, 21)]
    if [b["ordinal"] for b in blocks] != [19, 20, 21]:
        raise ValueError("COMPLETE_GUIDE_PAGES_REQUIRED")
    for block, page in zip(blocks, (20, 21, 22), strict=True):
        if not block["text"].startswith(f"[第 {page} 页；native；ready]"):
            raise ValueError("GUIDE_PAGE_IDENTITY")
    source = json.dumps({
        "source": {k: observation["source"][k] for k in
                   ("id", "filename", "sha256", "parse_id", "limitations")},
        "coverage": "指南物理页20–22（印刷页13–15）的完整既存文字块；保留原解析文本及其局限。",
        "blocks": blocks,
    }, ensure_ascii=False)
    commission = (
        "请对给定报告材料中§4.2（1）的施工季节X31与§4.2（5）的周边环境X42共同取值，"
        "完成两个指定谓词的独立规则符合性判断，逐条给出有来源依据的结果。"
        "以报告已采用的雨量、暂定施工条件与设施位置作为本次给定前提，不调查这些前提的现场真实性。"
        "材料可能包含报告其他部分，判断范围以所列两条标准为准；这不是整份报告验收、工程确认或签发。"
        "保留报告的阶段性和待确认说明并在其适用范围内理解。"
    )
    changed, edits = counterfactual(body)
    bodies = {"original": body, "target_counterfactual": changed}
    cases, conditions = [], []
    shared_rubric = rubric()
    for case_id, version, context in CASE_CONDITIONS:
        candidate, spans = focused(bodies[version]) if context == "local" else (bodies[version], [])
        cases.append({"id": case_id, "commission": commission, "source": source,
                      "rubric": shared_rubric, "candidate": candidate})
        conditions.append({"id": case_id, "version": version, "context": context,
                           "candidate_sha256": sha(candidate), "characters": len(candidate),
                           "exact_section_slices": spans})
    model_inputs = {"version": "context-controls-v1", "cases": cases}
    receipt = {
        "version": "context-controls-preparation-v2",
        "preparation_revision": 2,
        "superseded_unrun_draft": {
            "path": ".analysis/task038/model-inputs.json",
            "sha256": "13f36a8e3380f1658d79d5a755f40f797d5c475f1d1ef89a50f8da3f29ee7af3",
            "reason": "Before any model calls, distinguish the >800mm band from its >1000mm fixed-score note.",
        },
        "script_sha256": sha(Path(__file__).read_bytes()),
        "frozen_input_files": INPUT_HASHES,
        "draft_id": DRAFT_ID, "draft_body_sha256": DRAFT_SHA,
        "original_acceptance_id": ACCEPTANCE_ID, "original_acceptance_body_sha256": ACCEPTANCE_SHA,
        "original_criteria_reused_as_model_rubric": False,
        "guide_tool_call_id": GUIDE_CALL, "guide_public_request_sequence": 123,
        "guide_observation_sha256": GUIDE_OBSERVATION_SHA,
        "guide_blocks": [{"ordinal": b["ordinal"], "locator": b["locator"],
                          "text_sha256": sha(b["text"])} for b in blocks],
        "shared_field_sha256": {k: sha(cases[0][k]) for k in ("commission", "source", "rubric")},
        "criterion_ids": list(CRITERION_IDS),
        "transformations": edits,
        "counterfactual_full_body_sha256": sha(changed),
        "case_conditions": conditions,
        "model_inputs_sha256": sha(encoded(model_inputs)),
        "scope": "Target rule-membership diagnostic only; unchanged F values, levels and other defects are outside the criteria. No business report is modified.",
        "oracle_file": ".ase/verification/038-fixture-oracle.md",
        "oracle_or_prior_verdict_in_model_inputs": False,
    }
    # Frozen inputs are rehashed after construction; no SQLite connections or writes.
    checked_inputs(root)
    return model_inputs, receipt


def main(output: Path):
    model_inputs, receipt = build()
    outputs = {output / "model-inputs.json": encoded(model_inputs),
               output / "input-receipt.json": encoded(receipt)}
    for path, content in outputs.items():
        if path.exists() and path.read_bytes() != content:
            raise ValueError(f"REFUSE_DIFFERENT_EXISTING_OUTPUT: {path}")
    output.mkdir(parents=True, exist_ok=True)
    for path, content in outputs.items():
        if not path.exists():
            with path.open("xb") as stream:
                stream.write(content)
    print(json.dumps({"model_inputs": str(output / "model-inputs.json"),
                      "sha256": receipt["model_inputs_sha256"], "cases": len(model_inputs["cases"])},
                     ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".analysis/task038/frozen")
    main(parser.parse_args().output)

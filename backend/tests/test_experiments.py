"""Experiment Lab: analysis correctness and runner robustness (no FAISS / runtime needed)."""

import asyncio
import json

import pytest

import services.experiments as ex

Q = "Conveyor motor. Telemetry: temperature 65 °C, vibration 0.25, pressure 50 PSI, 2400 RPM."


def _run(i, answer, sigs, baseline=False, group="tolerance"):
    steps = [{"key": f"stage{j}#1", "position": j, "stage": f"stage{j}", "agent": None, "signature": s, "reason": ""}
             for j, s in enumerate(sigs)]
    return {"run_index": i, "is_baseline": baseline, "factor": None if baseline else "temperature", "value": 60 + i,
            "label": f"run {i}", "short": f"r{i}", "group": "baseline" if baseline else group, "question": Q,
            "config": {}, "status": "done", "trace_id": None, "answer": answer, "confidence": 0.5,
            "review_decision": "REQUIRES_HUMAN_REVIEW", "outcome": {"margin": 0.3}, "steps": steps}


def test_identical_answers_never_link_a_step():
    runs = [_run(0, "Normal", ["a", "x"], baseline=True)] + [_run(i, "Normal", ["a" if i % 2 else "b", "x"]) for i in range(1, 9)]
    a = ex.analyse(runs, runs[0], None, "robustness")
    assert a["first_divergent_step"] is None
    assert not any(s["answer_linked"] for s in a["step_divergence"])
    assert a["verdict"]["level"] == "stable"


def test_clean_split_links_the_step_and_singletons_do_not():
    runs = [_run(0, "Normal", ["a", "p"], baseline=True)]
    runs += [_run(i, "Normal", ["a", "p"]) for i in range(1, 5)]
    runs += [_run(i, "Gearbox", ["b", "p" if i != 5 else "q"]) for i in range(5, 9)]
    a = ex.analyse(runs, runs[0], None, "robustness")
    linked = {s["key"]: s["answer_linked"] for s in a["step_divergence"]}
    assert linked["stage0#1"] is True          # decision at stage0 separates the two answers
    assert linked["stage1#1"] is False         # only one run differs there: a singleton proves nothing
    assert a["first_divergent_step"] == "stage0#1"
    assert a["verdict"]["level"] == "fragile"


def test_thin_margin_is_never_called_stable():
    runs = [_run(0, "Normal", ["a"], baseline=True)] + [_run(i, "Normal", ["a"]) for i in range(1, 4)]
    runs[0]["outcome"]["margin"] = 0.03
    assert ex.analyse(runs, runs[0], None, "robustness")["verdict"]["level"] == "sensitive"


def test_no_verdict_before_the_experiment_finishes():
    runs = [_run(0, "Normal", ["a"], baseline=True), _run(1, "Normal", ["a"])]
    assert ex.analyse(runs, runs[0], None, "robustness", finished=False)["verdict"]["level"] == "incomplete"


def test_robustness_design_uses_sensor_tolerances_and_joint_runs():
    runs = ex.design_runs("robustness", {"question": Q, "factors": {"drop_evidence": 2},
                                         "bands": {"temperature": [40, 60]}})
    groups = [r["group"] for r in runs]
    assert groups.count("tolerance") == 8 and groups.count("joint") == 2 and groups.count("evidence") == 2
    assert groups.count("wide") == 4                      # temperature 65 is above its band
    rpm = [r for r in runs if r["factor"] == "rpm" and r["group"] == "tolerance"]
    assert {r["value"] for r in rpm} == {2376.0, 2424.0}  # rpm uses its own 1 % tolerance


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(ex, "DB_PATH", str(tmp_path / "exp.db"))
    monkeypatch.setattr(ex, "tag_trace", lambda *a, **k: None)
    monkeypatch.setattr(ex, "_runner_lock", asyncio.Lock())
    ex.init_experiment_tables()
    return tmp_path


def _result(label, record_ids=("R1", "R2", "R3")):
    ev = [{"evidence_id": f"EV-00{i + 1}", "record_id": r, "label": label, "source_type": "real"} for i, r in enumerate(record_ids)]
    return {"confidence": 0.7, "review_decision": "AUTO_RESOLVE", "final_diagnosis": label,
            "harness": {"trace_id": None, "predicted_label": label, "evidence": ev, "timeline": [],
                        "hypothesis_scores": [{"label": label, "score": 0.6}, {"label": "Other", "score": 0.2}],
                        "agents": {"human_review_coordinator": {"finding_label": label, "evidence_ids": ["EV-003"]}}}}


def test_runner_failures_cancel_resume_and_cited_evidence_first(tmp_db):
    calls, n = [], [0]

    async def diagnose(question, dataset, mode, top_k=8, exclude_record_ids=()):
        calls.append(list(exclude_record_ids))
        n[0] += 1
        if n[0] == 2:
            raise RuntimeError("boom")
        if n[0] == 3:
            return {"harness": {"timeline": [{"stage": "x", "reason": object()}]}, "confidence": object()}  # unserialisable
        return _result("Normal")

    spec = {"question": Q, "factors": {"drop_evidence": 2}, "bands": {}}
    exp_id = ex.create_experiment("t", "robustness", spec)

    async def go():
        ex.start_experiment(exp_id, diagnose)
        await ex._tasks[exp_id]
    asyncio.run(go())
    e = ex.get_experiment(exp_id)
    statuses = [r["status"] for r in e["runs"]]
    assert "running" not in statuses and statuses.count("failed") == 2
    assert e["status"] == "done" and e["verdict"] is not None
    drops = [c for c in calls if c]
    assert drops[0] == ["R3"]                       # the record the final diagnosis cites is dropped first
    # resume retries only the failed runs
    calls.clear()
    asyncio.run(go())
    assert len(calls) == 2
    assert [r["status"] for r in ex.get_experiment(exp_id)["runs"]].count("failed") == 0


def test_reviews_require_a_reason(tmp_db):
    with pytest.raises(ValueError):
        ex.add_review("TR-1", "approve", "  ", None, "me", None)
    ex.add_review("TR-1", "change", "bearing noise heard on site", "Bearing Wear", "me", None)
    assert ex.list_reviews("TR-1")[0]["final_label"] == "Bearing Wear"


# ─── step tables, second-check flags, confidence stability, step numbers ─────

def _st(key, sig, pos, **extra):
    stage = key.split("#")[0].split(":")[0]
    return {"key": key, "position": pos, "stage": stage, "agent": None, "signature": sig, "reason": "", **extra}


def _full(i, answer, review="REQUIRES_HUMAN_REVIEW", rag="real evidence → X", council=True, baseline=False, group="tolerance",
          conf=0.5, label=None, factor="temperature", value=None):
    steps = [_st("initial_rag#1", "real evidence → X", 0), _st("numerical_analysis#1", "X > Y", 1)]
    if rag:
        steps.append(_st("targeted_rag#1", rag, 2))
    if council:
        steps.append(_st("council#1", "council convened", 3))
    steps.append(_st("review_gate#1", review, 4))
    r = _run(i, answer, [], baseline=baseline, group=group)
    r.update(steps=steps, review_decision=review, confidence=conf, label=label or f"run {i}",
             factor=None if baseline else factor, value=value if value is not None else 60 + i)
    return r


def test_step_table_rows_always_add_up_to_all_runs():
    runs = [_run(0, "Normal", ["s0"], baseline=True)] + [_run(i, "Normal" if i % 2 else "Gearbox", [f"s{i}"]) for i in range(1, 9)]
    runs += [_run(9, "Gearbox", []), _run(10, "Normal", [])]          # two runs never reach the step
    a = ex.analyse(runs, runs[0], None, "sensor_sweep")
    d = a["step_divergence"][0]
    assert len(d["variants"]) == 6 and d["other_variants"]["count"] == 3
    assert sum(g["count"] for g in d["absent"]) == 2
    assert sum(sum(g["answers"].values()) for g in d["absent"]) == 2
    total = sum(v["count"] for v in d["variants"]) + d["other_variants"]["count"] + sum(g["count"] for g in d["absent"])
    assert total == a["completed_runs"] == 11
    assert sum(d["other_variants"]["answers"].values()) == 3


def test_second_check_detects_auto_approval_and_synthetic_double_check():
    auto = ex.second_check([_st("review_gate#1", "AUTO_RESOLVE", 0)], 0, "AUTO_RESOLVE")
    assert auto["auto_no_check"] and not auto["searched"] and not auto["council"]
    reviewed = ex.second_check([_st("targeted_rag#1", "real evidence → X", 0)], 1, "AUTO_RESOLVE")
    assert not reviewed["auto_no_check"]
    counted = ex.second_check([_st("targeted_rag#1", "mixed", 0, sources={"real": 7, "synthetic": 1})], 1, "REQUIRES_HUMAN_REVIEW")
    assert not counted["synthetic_only"] and counted["sources"] == {"real": 7, "synthetic": 1}
    old = ex.second_check([_st("targeted_rag#1", "synthetic evidence → X", 0), _st("targeted_rag#2", "no evidence", 1)], 2, None)
    assert old["synthetic_only"]


def test_auto_approved_flip_is_never_stable_and_wide_flips_are_named():
    runs = [_full(0, "Normal", baseline=True)] + [_full(i, "Normal") for i in range(1, 5)]
    runs.append(_full(5, "Pump Cavitation", review="AUTO_RESOLVE", rag=None, council=False, group="wide",
                      label="Temperature −40% → 39 °C", conf=0.67))
    a = ex.analyse(runs, runs[0], None, "robustness")
    v = a["verdict"]
    assert v["level"] == "sensitive"                       # would be "stable" without the unchecked flip
    assert "temperature −40%" in v["text"] and "auto-approved without a second check" in v["text"]
    assert v["auto_approved_flips"][0]["run_index"] == 5
    assert any(n["id"] == "auto_no_check" and "Pump Cavitation 67%" in n["text"] for n in a["notes"])
    d = next(x for x in a["step_divergence"] if x["key"] == "targeted_rag#1")
    assert d["absent"][0]["reason"].startswith("skipped") and d["absent"][0]["run_indexes"] == [5]


def test_synthetic_double_check_note_needs_three_runs_to_claim_a_link():
    def mk(n_syn):
        runs = [_full(0, "Normal", baseline=True)]
        runs += [_full(i, "Gearbox", rag="synthetic evidence → G") for i in range(1, n_syn + 1)]
        runs += [_full(i, "Normal") for i in range(n_syn + 1, n_syn + 5)]
        return next(n for n in ex.analyse(runs, runs[0], None, "sensor_sweep")["notes"] if n["id"] == "double_check_synthetic")["text"]
    assert mk(2).startswith("Suggestive (2 runs)") and "both changed the answer" in mk(2) and "Too few runs" in mk(2)
    assert mk(3).startswith("3 runs whose double-check found only synthetic evidence; 3 of them changed the answer")


def test_confidence_swing_and_band_crossing_are_reported():
    q = "Pump. Telemetry: current 75 A, temperature 65 °C."
    base = _full(0, "Normal", baseline=True, conf=0.35)
    up = _full(1, "Normal", conf=0.21, label="Current +3% → 77.2 A", factor="current", value=77.2)
    down = _full(2, "Normal", conf=0.33, label="Current −3% → 72.8 A", factor="current", value=72.8)
    for r in (base, up, down):
        r["question"] = q
    a = ex.analyse([base, up, down], base, None, "robustness", spec={"bands": {"current": [60, 76.1]}})
    st = a["confidence_stability"]
    assert st["largest"]["run_index"] == 1 and st["largest"]["pct"] == 3
    assert st["range_text"] == "confidence 21–35% under normal sensor error"
    text = next(n["text"] for n in a["notes"] if n["id"] == "confidence_unstable")
    assert "a 3% change in current moved it 14 points (35% → 21%)" in text and "76.1 A" in text


def test_step_numbers_follow_the_baseline_and_extra_steps_sit_where_they_ran():
    base = _full(0, "Normal", baseline=True, rag=None)
    other = _full(1, "Normal")
    a = ex.analyse([base, other], base, None)
    nums = a["step_numbers"]
    assert nums["initial_rag#1"] == 1 and nums["review_gate#1"] == 4
    assert nums["targeted_rag#1"] is None                      # the baseline never ran it: no baseline number
    order = [d["key"] for d in a["step_divergence"]]
    assert order.index("targeted_rag#1") == order.index("numerical_analysis#1") + 1   # placed where it ran


def test_linked_needs_a_real_lift_over_all_runs():
    # 9 of 10 runs reach Normal: a pure group of Normal runs adds little over the 90 % base rate
    runs = [_run(0, "Normal", ["a"], baseline=True)] + [_run(i, "Normal", ["a" if i < 5 else "b"]) for i in range(1, 9)]
    runs.append(_run(9, "Gearbox", ["c"]))
    d = ex.analyse(runs, runs[0], None)["step_divergence"][0]
    assert not d["answer_linked"]


def test_plain_signature_has_no_raw_plurals():
    assert ex.plain_signature("n numeric channel(s), 0 explicitly missing, 1 directional cue(s), equipment=x") == \
        "numeric readings, 0 explicitly missing, 1 directional cue, equipment=x"


def test_trace_signal_for_unchecked_auto_approval(monkeypatch):
    import services.trace_insights as ti
    monkeypatch.setattr(ti, "_trace_summary", lambda _t: {})
    snap = {"trace_id": "TR-1", "answer": "Normal", "confidence": 0.83, "review_decision": "AUTO_RESOLVE", "margin": 0.4,
            "feedback_rounds": 0, "council": {"convened": False}, "agents": {},
            "steps": [_st("review_gate:human_review_coordinator#1", "AUTO_RESOLVE", 0)]}
    ids = {s["id"] for s in ti.signals(snap)}
    assert "auto_no_second_check" in ids
    snap["steps"].insert(0, _st("targeted_rag#1", "synthetic evidence → X", 0, sources={"synthetic": 3}))
    snap["feedback_rounds"] = 1
    sig = {s["id"]: s for s in ti.signals(snap)}
    assert "auto_no_second_check" not in sig
    assert "3 synthetic" in sig["double_check_synthetic"]["detail"]

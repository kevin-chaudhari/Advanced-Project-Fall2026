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

import json
from pathlib import Path

import pandas as pd

from data_generator import synthetic_industrial_generator as gen
from data_loader.afrb_loader import AFRBLoader
from harness.canonical import parse_failure_iq_question

BACKEND = Path(__file__).resolve().parent.parent
SYN = BACKEND / "data" / "synthetic" / "afrb_synthetic.csv"
TESTS = BACKEND / "data" / "synthetic" / "test_scenarios.csv"


def test_synthetic_rows_carry_provenance():
    df = pd.read_csv(SYN)
    assert (df["Source_Type"] == "synthetic").all()
    assert df["Synthetic"].astype(str).str.lower().eq("true").all()
    assert df["Synthetic_Record_ID"].str.match(r"^SYN-\d{6}$").all()
    assert (df["Synthetic_Generator_Version"] == gen.GENERATOR_VERSION).all()
    assert df["Synthetic_Scenario"].notna().all()


def test_generator_is_deterministic_and_validates():
    a = gen.generate_knowledge_base(seed=1)
    b = gen.generate_knowledge_base(seed=1)
    pd.testing.assert_frame_equal(a, b)
    rep = gen.validate(a)
    assert rep["all_checks_passed"], rep
    assert rep["checks"]["duplicate_rate"] < 0.01


def test_generator_covers_gap_scenarios():
    labels = pd.read_csv(SYN).apply(lambda r: r["Option_" + r["Correct_Answer"]], axis=1)
    for needed in ["Normal Operation", "Seal Failure", "Pump Cavitation", "Gearbox Degradation"]:
        assert (labels == needed).sum() >= 100
    df = pd.read_csv(SYN)
    assert df[gen.SENSORS].isna().any(axis=1).sum() >= 500          # missing-sensor cases
    assert df["Synthetic_Scenario"].str.startswith("contradictory").sum() >= 100
    assert df["Synthetic_Scenario"].str.startswith("ambiguous").sum() >= 100


def test_test_scenarios_are_held_out():
    kb_ids = set(pd.read_csv(SYN)["Question_ID"])
    tests = pd.read_csv(TESTS, keep_default_na=False)
    assert not kb_ids & set(tests["case_id"])
    for cat in ["missing_temperature", "conflicting_signals", "no_historical_match", "ambiguous_failure", "normal_equipment"]:
        assert (tests["category"] == cat).sum() >= 10
    miss = tests[tests["category"] == "missing_temperature"]
    assert (miss["sensor_Temperature"] == "").all()
    assert not miss["question"].str.contains(r"temperature \d", regex=True).any()


def test_loader_keeps_missing_values_missing():
    recs = AFRBLoader(str(SYN)).load_records()
    with_missing = [r for r in recs if r.sensors["temperature"] is None]
    assert with_missing, "synthetic set must contain missing temperatures"
    assert all("Temperature: unavailable" in r.text for r in with_missing)
    assert all(r.source_type == "synthetic" for r in recs)
    assert all("Synthetic Scenario" not in r.text for r in recs)       # provenance never embedded


def test_failure_iq_polarity_is_parsed():
    p = parse_failure_iq_question("For electric motor, if a failure event rotor windings fault occurs, which "
                                  "sensors out of the choices are not relevant regarding the occurrence?")
    assert p["polarity"] == "irrelevant" and p["anchor"] == "rotor windings fault"
    assert p["equipment"] == "electric motor"

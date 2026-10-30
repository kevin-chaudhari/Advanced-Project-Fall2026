"""Checks for the REAL hydraulic-rig knowledge base (UCI #447, built by data/real/build_hydraulic_kb.py)."""

from pathlib import Path

import pandas as pd
import pytest

from data_loader.afrb_loader import AFRBLoader
from harness.rules import check_consistency

CSV = Path(__file__).resolve().parent.parent / "data" / "real" / "hydraulic_rig_cycles.csv"
pytestmark = pytest.mark.skipif(not CSV.exists(), reason="hydraulic_rig_cycles.csv not built")

LABELS = {"Cooling System Failure", "Valve Switching Degradation", "Internal Pump Leakage",
          "Accumulator Pressure Loss", "Normal Operation"}


def test_every_measured_cycle_is_present_and_real():
    df = pd.read_csv(CSV)
    assert len(df) == 2205
    assert df["Question_ID"].is_unique
    assert set(df["Source_Type"]) == {"real"}
    assert set(df["Failure_Mode"]) == LABELS


def test_unmeasured_channels_are_never_imputed():
    df = pd.read_csv(CSV)
    for col in ("RPM", "Current", "Voltage"):
        assert df[col].isna().all()
    recs = AFRBLoader(str(CSV)).load_records("hydraulic")
    assert all(r.sensors["rpm"] is None and r.sensors["current"] is None for r in recs)
    assert all(r.sensors["temperature"] is not None for r in recs)


def test_pressure_is_converted_bar_to_psi():
    df = pd.read_csv(CSV)
    assert ((df["Pressure"] - df["Pressure_Bar_PS1"] * 14.5038).abs() < 0.2).all()


def test_label_follows_documented_rule():
    df = pd.read_csv(CSV)
    healthy = (df.Cooler_Condition_Pct == 100) & (df.Valve_Condition_Pct == 100) & \
              (df.Internal_Pump_Leakage_Level == 0) & (df.Accumulator_Pressure_Bar == 130)
    assert (df.loc[healthy, "Failure_Mode"] == "Normal Operation").all()
    assert (df.loc[df.Cooler_Condition_Pct == 3, "Failure_Mode"] == "Cooling System Failure").all()


def test_hydraulic_pressures_pass_the_physical_range_check():
    df = pd.read_csv(CSV)
    assert not check_consistency({"pressure": float(df["Pressure"].max())})

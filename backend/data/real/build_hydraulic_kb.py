"""
Build the REAL hydraulic-rig knowledge base from the UCI "Condition monitoring of
hydraulic systems" dataset (Helwig, Pignanelli & Schütze, ZeMA gGmbH, 2015/2018;
UCI ML Repository #447, CC BY 4.0).

Every row of the output is one measured 60-second load cycle of a real hydraulic
test rig (2205 cycles).  Nothing is simulated or imputed here: each sensor value is
the mean of that sensor's samples over the cycle, and the fault label comes from the
rig's recorded component conditions (profile.txt).

Usage
-----
    python build_hydraulic_kb.py <folder with PS1.txt … profile.txt> [out.csv]

Required raw files: PS1, EPS1, FS1, TS1, VS1, CE, SE (.txt) and profile.txt.

Channel mapping onto the shared seven-channel schema
----------------------------------------------------
    Temperature  ← TS1 mean (°C)
    Vibration    ← VS1 mean (mm/s — NOT the AFRB normalised index; this knowledge
                   base has its own reference bands, so scales never mix)
    Pressure     ← PS1 mean, converted bar → PSI (× 14.5038) to match the schema unit
    Flow_Rate    ← FS1 mean (L/min)
    RPM, Current, Voltage ← not measured on this rig → left empty (never imputed)
Extra context columns (shown as evidence text, not used for numeric matching):
    motor power EPS1 (W), cooling efficiency CE (%), system efficiency SE (%),
    PS1 in bar, the four recorded component conditions and the stable flag.

Label rule (documented, deterministic)
--------------------------------------
The rig degrades four components independently, so most cycles have several
degraded components at once.  Each component condition is turned into an ordinal
severity using the dataset's own documentation:

    cooler  100 % full efficiency → 0 · 20 % reduced efficiency → 2 · 3 % close to total failure → 3
    valve   100 % optimal → 0 · 90 % small lag → 1 · 80 % severe lag → 2 · 73 % close to total failure → 3
    pump    0 no leakage → 0 · 1 weak leakage → 1 · 2 severe leakage → 2
    accumulator 130 bar optimal → 0 · 115 slightly reduced → 1 · 100 severely reduced → 2 · 90 close to total failure → 3

Failure_Mode = the component with the highest severity (ties broken in the fixed
order cooler → valve → pump → accumulator); every other degraded component is listed
in Secondary_Failure_Mode.  All four severities 0 → "Normal Operation".
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

BAR_TO_PSI = 14.5038
LABELS = {
    "cooler": "Cooling System Failure",
    "valve": "Valve Switching Degradation",
    "pump": "Internal Pump Leakage",
    "accumulator": "Accumulator Pressure Loss",
}
COMPONENT_NAMES = {"cooler": "cooler", "valve": "directional valve", "pump": "main pump", "accumulator": "hydraulic accumulator"}
COOLER_SEV = {100: 0, 20: 2, 3: 3}
VALVE_SEV = {100: 0, 90: 1, 80: 2, 73: 3}
PUMP_SEV = {0: 0, 1: 1, 2: 2}
ACC_SEV = {130: 0, 115: 1, 100: 2, 90: 3}
CONTEXT = "Hydraulic power unit with motor-driven main pump (ZeMA test rig, constant 60 s load cycle)"
REQUIRED = ["PS1", "EPS1", "FS1", "TS1", "VS1", "CE", "SE"]


def _cycle_means(folder: Path, name: str) -> np.ndarray:
    arr = np.loadtxt(folder / f"{name}.txt")
    if arr.shape[0] != 2205:
        raise ValueError(f"{name}.txt has {arr.shape[0]} cycles, expected 2205")
    return arr.mean(axis=1)


def build(folder: Path) -> pd.DataFrame:
    prof = np.loadtxt(folder / "profile.txt")
    if prof.shape != (2205, 5):
        raise ValueError(f"profile.txt has shape {prof.shape}, expected (2205, 5)")
    m = {s: _cycle_means(folder, s) for s in REQUIRED}
    rows = []
    for i in range(prof.shape[0]):
        cooler, valve, leak, acc, stable = (int(round(x)) for x in prof[i])
        sev = {"cooler": COOLER_SEV[cooler], "valve": VALVE_SEV[valve], "pump": PUMP_SEV[leak], "accumulator": ACC_SEV[acc]}
        degraded = [c for c in ("cooler", "valve", "pump", "accumulator") if sev[c] > 0]
        if degraded:
            primary = max(degraded, key=lambda c: sev[c])   # max() keeps the first of equal values → fixed tie order
            label = LABELS[primary]
            secondary = "; ".join(LABELS[c] for c in degraded if c != primary)
            component = COMPONENT_NAMES[primary]
        else:
            label, secondary, component = "Normal Operation", "", "None"
        rows.append({
            "Question_ID": f"HYD_{i + 1:05d}",
            "System_Context": CONTEXT,
            "Temperature": round(float(m["TS1"][i]), 2),
            "Vibration": round(float(m["VS1"][i]), 3),
            "Pressure": round(float(m["PS1"][i]) * BAR_TO_PSI, 1),
            "RPM": None,
            "Current": None,
            "Voltage": None,
            "Flow_Rate": round(float(m["FS1"][i]), 3),
            "Failure_Mode": label,
            "Component": component,
            "Pressure_Bar_PS1": round(float(m["PS1"][i]), 2),
            "Motor_Power_W": round(float(m["EPS1"][i]), 1),
            "Cooling_Efficiency_Pct": round(float(m["CE"][i]), 2),
            "System_Efficiency_Pct": round(float(m["SE"][i]), 2),
            "Cooler_Condition_Pct": cooler,
            "Valve_Condition_Pct": valve,
            "Internal_Pump_Leakage_Level": leak,
            "Accumulator_Pressure_Bar": acc,
            "Stable_Conditions": "yes" if stable == 0 else "no (static conditions may not have been reached)",
            "Secondary_Failure_Mode": secondary,
            "Source_Type": "real",
            "Data_Source": "UCI #447 Condition monitoring of hydraulic systems (ZeMA), cycle " + str(i + 1),
        })
    return pd.DataFrame(rows)


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    folder = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).with_name("hydraulic_rig_cycles.csv")
    df = build(folder)
    df.to_csv(out, index=False)
    print(f"Wrote {len(df)} real cycles → {out}")
    print(df["Failure_Mode"].value_counts().to_string())


if __name__ == "__main__":
    main()

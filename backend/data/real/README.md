# Real hydraulic-rig knowledge base

`hydraulic_rig_cycles.csv` contains **2,205 real, measured load cycles** from the ZeMA hydraulic test rig.
It is served as its own knowledge base (`dataset_type = "hydraulic"`, REAL partition only) and has its own
FAISS index, reference bands and label signatures, so its units never mix with AFRB.

**Source:** Helwig, N., Pignanelli, E., & Schütze, A. (2015). *Condition monitoring of hydraulic systems* [Dataset].
UCI Machine Learning Repository. https://doi.org/10.24432/C5CW21. Licence: CC BY 4.0.

## Rebuild

```bash
# raw files: PS1, EPS1, FS1, TS1, VS1, CE, SE, profile (.txt) from the UCI download
python data/real/build_hydraulic_kb.py <raw folder> data/real/hydraulic_rig_cycles.csv
```

Delete `faiss_indexes/hydraulic.*` (or call `POST /rebuild-index?dataset_type=hydraulic`) after rebuilding.

## What each row is

| Column | From | Unit |
|---|---|---|
| Temperature | TS1 mean over the 60 s cycle | °C |
| Vibration | VS1 mean | mm/s (not the AFRB 0–1 index) |
| Pressure | PS1 mean × 14.5038 | PSI (PS1 in bar kept as `Pressure_Bar_PS1`) |
| Flow_Rate | FS1 mean | L/min |
| RPM, Current, Voltage | not measured on this rig | left empty, never imputed |
| Motor_Power_W, Cooling/System_Efficiency_Pct | EPS1, CE, SE means | W, % |
| Cooler/Valve/Pump/Accumulator condition | `profile.txt` (recorded rig state) | as documented |

## Labels

The rig degrades four components independently, so most cycles have several degraded components.
`Failure_Mode` is the most severe one (severity from the dataset documentation; ties broken
cooler → valve → pump → accumulator), and the others go in `Secondary_Failure_Mode`.

| Failure_Mode | Cycles |
|---|---|
| Cooling System Failure | 1,041 |
| Accumulator Pressure Loss | 688 |
| Valve Switching Degradation | 370 |
| Internal Pump Leakage | 85 |
| Normal Operation | 21 |

Per-cycle means capture cooler degradation strongly (oil temperature) but valve, pump and accumulator
wear only weakly; those faults mainly show in transients that a cycle mean averages out.

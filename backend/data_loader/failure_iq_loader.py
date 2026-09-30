"""
Failure IQ Dataset Loader (FailureSensorIQ CSV).

The CSV is a sensor/failure-event relevance benchmark.  Each row asks either
"which SENSORS are (ir)relevant for failure event X on equipment E" or
"which FAILURE EVENTS are (ir)relevant when sensor S is abnormal on E".

Fixes vs. the original loader
-----------------------------
* **Polarity**: roughly half of the questions ask for *non-relevant* items
  ("not relevant", "irrelevant", "excluded" …).  The original loader always
  wrote the correct options as "Relevant Sensors (correct)", which inverted
  the meaning of those records and fed wrong facts to the agents.  The loader
  now parses polarity and writes explicit "Relevant … / Not relevant …" lines.
* Equipment / anchor parsing (the original left 470/500 docs with
  "Equipment: industrial equipment" and "Failure Event: unknown").
* All rows are loaded by default (5,629) instead of a random 500-row sample.
* The randomly generated 30-row "synthetic supplement" is disabled by default
  (it produced random, meaningless combinations).  It is only used as a
  fallback when the CSV is missing and is then labelled ``source_type=synthetic``.
"""

import csv
import random
from pathlib import Path
from typing import Dict, List

from harness.canonical import CanonicalRecord, failure_iq_row_to_record
from utils.logger import setup_logger

logger = setup_logger(__name__)

_DEFAULT_CSV = Path(__file__).parent.parent / "data" / "failureiqsensor_sample.csv"

_SUPPLEMENT_EQUIPMENT = ["Centrifugal Pump", "Induction Motor", "Compressor", "Gearbox", "Turbine"]
_SUPPLEMENT_FAILURE_MODES = ["Bearing Wear", "Cavitation", "Misalignment", "Overheating", "Seal Failure"]
_SUPPLEMENT_SENSORS = ["vibration", "temperature", "current", "pressure", "flow rate"]


def _generate_supplement(n: int = 50) -> List[CanonicalRecord]:
    """Fallback only (CSV missing).  Clearly marked SYNTHETIC."""
    rng = random.Random(7)
    recs = []
    for i in range(n):
        eq = rng.choice(_SUPPLEMENT_EQUIPMENT)
        fm = rng.choice(_SUPPLEMENT_FAILURE_MODES)
        sensors = rng.sample(_SUPPLEMENT_SENSORS, k=2)
        text = (f"Equipment: {eq}\nFailure Event: {fm.lower()}\nRelevant sensors: {', '.join(sensors)}\n"
                "Source Type: SYNTHETIC (fallback supplement)")
        recs.append(CanonicalRecord(
            record_id=f"FIQ-SYN-{i + 1:04d}", dataset="failure_iq", source_type="synthetic",
            label=fm.lower(), text=text, system_context=eq, equipment_type=None,
            synthetic_scenario="failure_iq_fallback_supplement", generator_version="legacy",
            extra={"anchor": fm.lower(), "anchor_type": "failure_event", "polarity": "relevant",
                   "asks_for": "sensors", "relevant_items": sensors, "irrelevant_items": []}))
    return recs


class FailureIQLoader:
    def __init__(self, csv_path: str | None = None, sample_size: int | None = None,
                 supplement_size: int = 0):
        self.csv_path = Path(csv_path) if csv_path else _DEFAULT_CSV
        self.sample_size = sample_size
        self.supplement_size = supplement_size

    def load_records(self) -> List[CanonicalRecord]:
        if self.csv_path.exists():
            try:
                with open(self.csv_path, newline="", encoding="utf-8") as fh:
                    rows = list(csv.DictReader(fh))
                if self.sample_size and len(rows) > self.sample_size:
                    rows = random.Random(523).sample(rows, self.sample_size)
                recs = [failure_iq_row_to_record(r) for r in rows]
                if self.supplement_size:
                    recs += _generate_supplement(self.supplement_size)
                logger.info("Loaded %d FailureSensorIQ records.", len(recs))
                return recs
            except Exception as exc:
                logger.warning("Could not read %s (%s) — using labelled synthetic fallback.", self.csv_path, exc)
        else:
            logger.warning("FailureSensorIQ CSV not found at %s — using labelled synthetic fallback.", self.csv_path)
        return _generate_supplement(50)

    def load(self) -> List[Dict]:
        from data_loader.afrb_loader import record_to_document
        return [record_to_document(r) for r in self.load_records()]

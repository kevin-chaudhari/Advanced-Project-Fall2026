import os
import sys
from pathlib import Path

import pandas as pd
import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("HARNESS_USE_LLM", "false")
os.environ.setdefault("LOG_LEVEL", "WARNING")


@pytest.fixture(scope="session")
def small_kb(tmp_path_factory):
    """A small AFRB knowledge base (4k real + all synthetic rows), numeric/metadata
    stages only (no embedder) so tests run fast and offline."""
    from data_loader.afrb_loader import AFRBLoader
    from harness.knowledge_base import KnowledgeBase

    tmp = tmp_path_factory.mktemp("kb")
    real = pd.read_csv(BACKEND / "data" / "afrb_sample.csv", nrows=4000)
    real_path = tmp / "real.csv"
    real.to_csv(real_path, index=False)
    kb = KnowledgeBase("afrb")
    kb.add_partition("real", "afrb", AFRBLoader(str(real_path)).load_records("afrb"), semantic_ok=False)
    kb.add_partition("synthetic", "afrb_synthetic",
                     AFRBLoader(str(BACKEND / "data" / "synthetic" / "afrb_synthetic.csv")).load_records("afrb"),
                     semantic_ok=False)
    for m in kb.available_modes():
        kb.reference(m)
    return kb


@pytest.fixture(scope="session")
def orchestrator():
    from agents.orchestrator import AgentOrchestrator
    return AgentOrchestrator()

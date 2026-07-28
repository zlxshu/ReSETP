from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from dr_alns_ppo.learned_destroy import customer_arrays
from dr_alns_ppo.pilot20_learned_destroy_phaseA import DEFAULT_WORKER, _worker_integrity_ok
from dr_alns_ppo.schemas import LearnedDestroyDecodedAction
from dr_alns_ppo.worker_client import WorkerClient, _worker_env


REPO_ROOT = Path(__file__).resolve().parents[3]
FIFTY_CUSTOMER_BUNDLE = "models/data_bundle/generated_instances/E-UK50_11__curric_d2_s3_seed2251_24h"


def test_worker_env_enables_crash_diagnostics(tmp_path: Path) -> None:
    env = _worker_env(REPO_ROOT, crash_log_dir=tmp_path)

    assert env["PYTHONFAULTHANDLER"] == "1"
    assert Path(env["SETP_WORKER_CRASH_LOG_DIR"]) == tmp_path


def test_learned_destroy_50c_large_removal_block_steps_do_not_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    if not DEFAULT_WORKER.exists():
        pytest.skip("py313 solver worker is not available")
    if not (REPO_ROOT / FIFTY_CUSTOMER_BUNDLE).is_dir():
        pytest.skip("Track22-R 50c fresh bundle is not available")
    monkeypatch.setenv("SETP_WORKER_PYTHON", str(DEFAULT_WORKER))

    client = WorkerClient(FIFTY_CUSTOMER_BUNDLE, seed=2601, max_evals=80)
    try:
        response = client.reset()
        for step_index in range(50):
            _features, mask, customer_ids = customer_arrays(response["customer_features"], max_customers=128)
            active = [customer_ids[idx] for idx in np.flatnonzero(mask)]
            remove_count = min(20, max(1, math.ceil(0.4 * len(active))))
            action = LearnedDestroyDecodedAction(
                repair_id="regret2_insert_repair",
                q_ratio=0.4,
                threshold_ratio=0.0,
                block_size=1,
                remove_customer_ids=tuple(active[:remove_count]),
                raw=(step_index, remove_count),
            )
            response = client.block_step(action)
            assert response["ok"] is True
            assert response["violation_count"] == 0
            assert _worker_integrity_ok(response["trace"])
    finally:
        client.close()

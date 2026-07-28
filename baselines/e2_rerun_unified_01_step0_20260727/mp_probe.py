#!/usr/bin/env python3
from __future__ import annotations

import json
import multiprocessing as mp
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor


def worker(index: int) -> dict[str, int]:
    time.sleep(1.0)
    return {"index": index, "pid": os.getpid(), "ppid": os.getppid()}


def main() -> None:
    context = mp.get_context("spawn")
    with ProcessPoolExecutor(max_workers=6, mp_context=context) as pool:
        rows = list(pool.map(worker, range(6)))
    payload = {
        "python": sys.executable,
        "start_method": context.get_start_method(),
        "requested_workers": 6,
        "distinct_pids": len({row["pid"] for row in rows}),
        "rows": rows,
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    if payload["distinct_pids"] != 6:
        raise SystemExit("six distinct workers were not materialized")


if __name__ == "__main__":
    main()

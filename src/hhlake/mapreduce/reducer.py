import csv
import io
import json
import os
import pickle
import sys
from collections import Counter
from itertools import groupby
from pathlib import Path

from hhlake.mapreduce.tasks import SEP, Key, ReduceTask, commit_dir
from hhlake.s3 import make_client
from hhlake.settings import STACK_NAMES

TOP = 10
CRASH_EXIT_CODE = 13


def _shuffle_combined(files: list[Path]) -> Counter[Key]:
    total: Counter[Key] = Counter()
    for path in files:
        total.update(pickle.loads(path.read_bytes()))
    return total


def _shuffle_sorted(files: list[Path]) -> Counter[Key]:
    records: list[str] = []
    for path in files:
        records.extend(path.read_text(encoding="utf-8").splitlines())
    records.sort()
    total: Counter[Key] = Counter()
    for key, group in groupby(records, key=lambda rec: rec.rsplit("\t", 1)[0]):
        total[tuple(key.split(SEP))] = sum(int(rec.rsplit("\t", 1)[1]) for rec in group)
    return total


def _to_csv(size: int, counts: Counter[Key]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow([f"skill{i}" for i in range(1, size + 1)] + ["vacancies"])
    for key, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        writer.writerow([*key, n])
    return buf.getvalue().encode("utf-8")


def run_reduce(task: ReduceTask) -> None:
    job = task.job
    s3 = make_client()
    map_root = Path(job.workdir) / "map"
    summary: dict[int, dict] = {}
    for k in job.stack_sizes:
        suffix = ".pkl" if job.combiner else ".txt"
        files = sorted(map_root.glob(f"m[0-9][0-9][0-9][0-9]/k{k}-r{task.partition:03d}{suffix}"))
        counts = _shuffle_combined(files) if job.combiner else _shuffle_sorted(files)
        key = f"{task.output_prefix}/{STACK_NAMES[k]}/part-r-{task.partition:05d}.csv"
        s3.put_object(Bucket=job.bucket, Key=key, Body=_to_csv(k, counts), ContentType="text/csv")
        if task.crash:
            print(f"[reduce r{task.partition:03d} attempt {task.attempt}] simulated crash after writing {key}")
            sys.stdout.flush()
            os._exit(CRASH_EXIT_CODE)
        summary[k] = {
            "inputs": len(files),
            "distinct": len(counts),
            "total": sum(counts.values()),
            "top": [[list(key), n] for key, n in counts.most_common(TOP)],
        }
    out = Path(job.workdir) / "reduce"
    tmp = out / f"r{task.partition:03d}.attempt{task.attempt}.tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "summary.json").write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
    commit_dir(tmp, out / f"r{task.partition:03d}")

import argparse
import csv
import json
import shutil
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pyarrow.parquet as pq

from hhlake.mapreduce.pool import Finished, ProcessPerTask, Task, Watchdog, WorkerPool, drive, task_name
from hhlake.mapreduce.s3file import S3RangeFile
from hhlake.mapreduce.splits import Split, plan_splits
from hhlake.mapreduce.tasks import JobSpec, MapTask, ReduceTask, map_dir
from hhlake.s3 import make_client
from hhlake.settings import BUCKET, RAW_KEY, STACK_NAMES

PARQUET_COLUMNS = ("role", "name", "key_skills")
KILL_AFTER = 2.0


class JobFailed(RuntimeError):
    pass


@dataclass
class Attempt:
    name: str
    attempt: int
    exitcode: int | None
    seconds: float


@dataclass
class PhaseReport:
    name: str
    tasks: int
    seconds: float = 0.0
    attempts: list[Attempt] = field(default_factory=list)

    @property
    def failed(self) -> list[Attempt]:
        return [a for a in self.attempts if a.exitcode != 0]


class Scheduler:
    def __init__(self, workers: int, max_attempts: int, reuse: bool, watchdog: Watchdog) -> None:
        pool_cls = WorkerPool if reuse else ProcessPerTask
        self.pool: WorkerPool | ProcessPerTask = pool_cls(workers, watchdog)
        self.max_attempts = max_attempts

    def run(
        self,
        phase: str,
        tasks: list[Task],
        retry: Callable[[Task], Task],
        committed: Callable[[Task], bool],
    ) -> PhaseReport:
        report = PhaseReport(phase, len(tasks))
        t0 = time.perf_counter()
        self.pool.start()

        def on_finished(fin: Finished) -> Task | None:
            task = fin.task
            ok = fin.exitcode == 0 and committed(task)
            code = fin.exitcode
            if code == 0 and not ok:
                code = -1
            attempt = Attempt(task_name(task), task.attempt, code, fin.seconds)
            report.attempts.append(attempt)
            if ok:
                return None
            print(f"[master] {attempt.name} attempt {attempt.attempt} FAILED (exit code {fin.exitcode})", end="")
            if task.attempt >= self.max_attempts:
                print(" -> giving up")
                raise JobFailed(f"{attempt.name} failed {task.attempt} times")
            print(f" -> rescheduled as attempt {task.attempt + 1}")
            return retry(task)

        drive(self.pool, tasks, on_finished)
        report.seconds = time.perf_counter() - t0
        return report

    def close(self) -> int:
        self.pool.close()
        return self.pool.spawned


def _read_header(bucket: str, key: str) -> dict[str, int]:
    head = make_client().get_object(Bucket=bucket, Key=key, Range="bytes=0-65535")["Body"].read()
    line = head.split(b"\n", 1)[0].decode("utf-8")
    return {name: i for i, name in enumerate(next(csv.reader([line])))}


def _row_group_splits(bucket: str, key: str, size: int) -> list[Split]:
    meta = pq.ParquetFile(S3RangeFile(make_client(), bucket, key, size)).metadata
    splits = []
    for i in range(meta.num_row_groups):
        rg = meta.row_group(i)
        start = min(_chunk_start(rg.column(c)) for c in range(rg.num_columns))
        compressed = sum(rg.column(c).total_compressed_size for c in range(rg.num_columns))
        splits.append(Split(i, start, start + compressed))
    return splits


def _chunk_start(col: pq.ColumnChunkMetaData) -> int:
    if col.has_dictionary_page and col.dictionary_page_offset:
        return int(col.dictionary_page_offset)
    return int(col.data_page_offset)


def _clear_prefix(bucket: str, prefix: str) -> int:
    s3 = make_client()
    removed = 0
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix + "/"):
        keys = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
        if keys:
            s3.delete_objects(Bucket=bucket, Delete={"Objects": keys})
            removed += len(keys)
    return removed


@dataclass
class JobConfig:
    bucket: str
    key: str
    output: str
    chunk_mb: int
    workers: int
    reducers: int
    combiner: bool
    prefilter: bool
    fail_read: list[int]
    fail_commit: list[int]
    fail_reduce: list[int]
    kill_map: list[int]
    task_timeout: float | None
    max_attempts: int
    reuse: bool
    workdir: Path
    keep: bool


def _merge_summaries(job: JobSpec) -> dict[int, dict]:
    merged: dict[int, dict] = {}
    for path in sorted((Path(job.workdir) / "reduce").glob("r[0-9][0-9][0-9]/summary.json")):
        for k, part in json.loads(path.read_text(encoding="utf-8")).items():
            acc = merged.setdefault(int(k), {"distinct": 0, "total": 0, "top": []})
            acc["distinct"] += part["distinct"]
            acc["total"] += part["total"]
            acc["top"].extend(part["top"])
    for acc in merged.values():
        acc["top"] = sorted(acc["top"], key=lambda kv: (-kv[1], kv[0]))[:10]
    return merged


def _map_totals(job: JobSpec, splits: list[Split]) -> dict:
    totals: dict = {
        "bytes_fetched": 0,
        "cpu_seconds": 0.0,
        "lines": 0,
        "parsed": 0,
        "in_variant": 0,
        "with_skills": 0,
        "emitted": {},
        "written": {},
    }
    for split in splits:
        stats = json.loads((map_dir(job, split.index) / "stats.json").read_text(encoding="utf-8"))
        for name in ("bytes_fetched", "cpu_seconds", "lines", "parsed", "in_variant", "with_skills"):
            totals[name] += stats[name]
        for name in ("emitted", "written"):
            for k, v in stats[name].items():
                totals[name][int(k)] = totals[name].get(int(k), 0) + v
    return totals


def run_job(cfg: JobConfig) -> dict:
    t0 = time.perf_counter()
    size = make_client().head_object(Bucket=cfg.bucket, Key=cfg.key)["ContentLength"]
    workdir = cfg.workdir / f"job-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    fmt = "parquet" if cfg.key.endswith(".parquet") else "csv"
    if fmt == "parquet":
        columns = {name: i for i, name in enumerate(PARQUET_COLUMNS)}
        splits = _row_group_splits(cfg.bucket, cfg.key, size)
        layout = f"{len(splits)} row groups, columns {', '.join(PARQUET_COLUMNS)}"
    else:
        columns = _read_header(cfg.bucket, cfg.key)
        splits = plan_splits(size, cfg.chunk_mb << 20)
        layout = f"{len(splits)} splits x {cfg.chunk_mb} MiB"
    job = JobSpec(cfg.bucket, cfg.key, size, columns, str(workdir), cfg.reducers, cfg.combiner, cfg.prefilter, fmt)
    t_clear = time.perf_counter()
    removed = _clear_prefix(cfg.bucket, cfg.output)
    t_clear = time.perf_counter() - t_clear
    print(f"[master] input s3://{cfg.bucket}/{cfg.key}: {size:,} bytes -> {layout}")
    print(
        f"[master] workers={cfg.workers} reducers={cfg.reducers} combiner={cfg.combiner} "
        f"prefilter={cfg.prefilter} reuse={cfg.reuse}"
    )
    print(f"[master] workdir {workdir}")
    print(f"[master] cleared {removed} old objects under s3://{cfg.bucket}/{cfg.output}/ ({t_clear:.2f} s)")

    crash = {i: "read" for i in cfg.fail_read} | {i: "commit" for i in cfg.fail_commit}
    watchdog = Watchdog(cfg.task_timeout, {f"m{i:04d}": KILL_AFTER for i in cfg.kill_map})
    scheduler = Scheduler(cfg.workers, cfg.max_attempts, cfg.reuse, watchdog)
    try:
        map_tasks: list[Task] = [MapTask(job, s, 1, crash.get(s.index)) for s in splits]
        map_report = scheduler.run(
            "map",
            map_tasks,
            retry=lambda t: MapTask(job, t.split, t.attempt + 1, None) if isinstance(t, MapTask) else t,
            committed=lambda t: isinstance(t, MapTask) and map_dir(job, t.split.index).exists(),
        )
        totals = _map_totals(job, splits)
        print(
            f"[master] map phase: {map_report.seconds:.2f} s, {len(map_report.attempts)} attempts, "
            f"{len(map_report.failed)} failed"
        )
        reduce_tasks: list[Task] = [
            ReduceTask(job, r, cfg.output, 1, r in cfg.fail_reduce) for r in range(cfg.reducers)
        ]
        reduce_report = scheduler.run(
            "reduce",
            reduce_tasks,
            retry=lambda t: (
                ReduceTask(job, t.partition, t.output_prefix, t.attempt + 1) if isinstance(t, ReduceTask) else t
            ),
            committed=lambda t: (
                isinstance(t, ReduceTask) and (Path(job.workdir) / "reduce" / f"r{t.partition:03d}").exists()
            ),
        )
        print(
            f"[master] reduce phase: {reduce_report.seconds:.2f} s, {len(reduce_report.attempts)} attempts, "
            f"{len(reduce_report.failed)} failed"
        )
    finally:
        spawned = scheduler.close()
    print(f"[master] worker processes spawned: {spawned} ({'reused across tasks' if cfg.reuse else 'one per task'})")
    merged = _merge_summaries(job)
    for k, name in STACK_NAMES.items():
        if merged[k]["total"] != totals["emitted"][k]:
            raise JobFailed(f"{name}: reduced {merged[k]['total']} != emitted {totals['emitted'][k]}, no _SUCCESS")
    leftovers = sorted(p.name for p in (Path(job.workdir) / "map").glob("*.tmp"))
    if leftovers:
        print(f"[master] uncommitted attempt dirs ignored: {', '.join(leftovers)}")
    elapsed = time.perf_counter() - t0

    result = {
        "input": f"s3://{cfg.bucket}/{cfg.key}",
        "output": f"s3://{cfg.bucket}/{cfg.output}",
        "size": size,
        "splits": len(splits),
        "chunk_mb": cfg.chunk_mb,
        "workers": cfg.workers,
        "reducers": cfg.reducers,
        "combiner": cfg.combiner,
        "prefilter": cfg.prefilter,
        "reuse": cfg.reuse,
        "format": fmt,
        "map": totals,
        "stacks": merged,
        "phases": [asdict(map_report), asdict(reduce_report)],
        "seconds": elapsed,
    }
    s3 = make_client()
    body = json.dumps(result, ensure_ascii=False, indent=1).encode("utf-8")
    s3.put_object(Bucket=cfg.bucket, Key=f"{cfg.output}/_job.json", Body=body)
    s3.put_object(Bucket=cfg.bucket, Key=f"{cfg.output}/_SUCCESS", Body=b"")
    if not cfg.keep:
        shutil.rmtree(workdir, ignore_errors=True)
    return result


def print_result(result: dict) -> None:
    m = result["map"]
    ratio = m["bytes_fetched"] / result["size"]
    print(
        f"[master] fetched {m['bytes_fetched']:,} bytes ({ratio:.4f} x input), lines {m['lines']:,}, "
        f"csv-parsed {m['parsed']:,}"
    )
    print(f"[master] variant vacancies: {m['in_variant']:,}, with key_skills: {m['with_skills']:,}")
    print(f"[master] map CPU time, all tasks: {m['cpu_seconds']:.1f} s")
    print(f"{'stack':<8}{'emitted':>12}{'after combine':>15}{'distinct':>10}{'sum count':>12}")
    for k, name in STACK_NAMES.items():
        st = result["stacks"][k]
        print(f"{name:<8}{m['emitted'][k]:>12,}{m['written'][k]:>15,}{st['distinct']:>10,}{st['total']:>12,}")
    for k, name in STACK_NAMES.items():
        print(f"-- top {name}")
        for key, n in result["stacks"][k]["top"]:
            print(f"  {n:>5}  {' + '.join(key)}")
    print(f"[master] output {result['output']}/{{skills,pairs,triples}}/part-r-*.csv, total {result['seconds']:.2f} s")


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m hhlake.mapreduce", description="skills / pairs / triples via MapReduce")
    p.add_argument("--bucket", default=BUCKET)
    p.add_argument("--key", default=RAW_KEY)
    p.add_argument("--output", default="results/mapreduce")
    p.add_argument("--chunk-mb", type=int, default=32)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--reducers", type=int, default=4)
    p.add_argument("--no-combiner", dest="combiner", action="store_false")
    p.add_argument("--no-prefilter", dest="prefilter", action="store_false")
    p.add_argument("--fail-map", type=int, action="append", default=[], help="kill map task N mid-read")
    p.add_argument("--fail-map-commit", type=int, action="append", default=[], help="kill map task N before commit")
    p.add_argument("--fail-reduce", type=int, action="append", default=[], help="crash reduce task N after 1st part")
    p.add_argument("--kill-map", type=int, action="append", default=[], help="master kills worker of map task N")
    p.add_argument("--task-timeout", type=float, default=600.0, help="kill and retry tasks running longer")
    p.add_argument("--max-attempts", type=int, default=3)
    p.add_argument("--no-reuse", dest="reuse", action="store_false", help="spawn a new process for every task")
    p.add_argument("--workdir", type=Path, default=Path("work"))
    p.add_argument("--keep-work", dest="keep", action="store_true")
    a = p.parse_args()
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[union-attr]
    cfg = JobConfig(
        a.bucket,
        a.key,
        a.output,
        a.chunk_mb,
        a.workers,
        a.reducers,
        a.combiner,
        a.prefilter,
        a.fail_map,
        a.fail_map_commit,
        a.fail_reduce,
        a.kill_map,
        a.task_timeout,
        a.max_attempts,
        a.reuse,
        a.workdir,
        a.keep,
    )
    result = run_job(cfg)
    print_result(result)


if __name__ == "__main__":
    main()

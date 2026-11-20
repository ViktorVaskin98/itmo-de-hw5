import csv
import os
import sys
import time
from collections import Counter
from collections.abc import Iterator

import pyarrow.compute as pc
import pyarrow.parquet as pq

from hhlake.mapreduce.s3file import S3RangeFile
from hhlake.mapreduce.splits import iter_split_lines, split_chunks
from hhlake.mapreduce.tasks import (
    Key,
    MapStats,
    MapTask,
    commit_dir,
    map_dir,
    map_tmp_dir,
    partition_of,
    write_partitions,
    write_stats,
)
from hhlake.s3 import make_client
from hhlake.variant import ROLE, ROLE_BYTES, in_variant, parse_skills, stacks

CRASH_EXIT_CODE = 13


class _Meter:
    def __init__(self, chunks: Iterator[bytes]) -> None:
        self.chunks = chunks
        self.total = 0

    def __iter__(self) -> Iterator[bytes]:
        for chunk in self.chunks:
            self.total += len(chunk)
            yield chunk


def _crash(task: MapTask, what: str) -> None:
    print(f"[map m{task.split.index:04d} attempt {task.attempt}] simulated crash {what}")
    sys.stdout.flush()
    os._exit(CRASH_EXIT_CODE)


def _parquet_records(task: MapTask, stats: MapStats) -> Iterator[list[str]]:
    job = task.job
    src = S3RangeFile(make_client(), job.bucket, job.key, job.size)
    table = pq.ParquetFile(src).read_row_group(task.split.index, columns=list(job.columns))
    stats.lines = table.num_rows
    stats.bytes_fetched = src.fetched
    if task.crash == "read":
        _crash(task, f"after reading row group {task.split.index}")
    if job.prefilter:
        table = table.filter(pc.equal(table["role"], ROLE))
    stats.parsed = table.num_rows
    cols = [table.column(c).to_pylist() for c in job.columns]
    for row in zip(*cols, strict=True):
        yield [v or "" for v in row]


def _csv_records(task: MapTask, stats: MapStats) -> Iterator[list[str]]:
    job, split = task.job, task.split
    meter = _Meter(split_chunks(make_client(), job.bucket, job.key, split, job.size))
    for line in iter_split_lines(iter(meter), split):
        stats.lines += 1
        stats.bytes_fetched = meter.total
        if task.crash == "read" and meter.total >= split.length // 2:
            _crash(task, f"after {meter.total} bytes")
        if job.prefilter and ROLE_BYTES not in line:
            continue
        stats.parsed += 1
        yield next(csv.reader([line.decode("utf-8")]))


def run_map(task: MapTask) -> None:
    job = task.job
    cpu0 = time.process_time()
    stats = MapStats(split=task.split.index, attempt=task.attempt)
    role_i, name_i, skills_i = job.columns["role"], job.columns["name"], job.columns["key_skills"]
    combined = {k: [Counter[Key]() for _ in range(job.reducers)] for k in job.stack_sizes}
    raw = {k: [list[Key]() for _ in range(job.reducers)] for k in job.stack_sizes}
    stats.emitted = dict.fromkeys(job.stack_sizes, 0)

    records = _parquet_records if job.fmt == "parquet" else _csv_records
    for row in records(task, stats):
        if not in_variant(row[role_i], row[name_i]):
            continue
        stats.in_variant += 1
        skills = parse_skills(row[skills_i])
        if not skills:
            continue
        stats.with_skills += 1
        for k in job.stack_sizes:
            for key in stacks(skills, k):
                r = partition_of(key, job.reducers)
                if job.combiner:
                    combined[k][r][key] += 1
                else:
                    raw[k][r].append(key)
                stats.emitted[k] += 1

    tmp = map_tmp_dir(job, task.split.index, task.attempt)
    tmp.mkdir(parents=True, exist_ok=True)
    for k in job.stack_sizes:
        parts = combined[k] if job.combiner else raw[k]
        write_partitions(tmp, k, parts)
        stats.written[k] = sum(len(p) for p in parts)
    stats.cpu_seconds = time.process_time() - cpu0
    write_stats(tmp, stats)
    if task.crash == "commit":
        _crash(task, f"before commit, {tmp.name} left")
    commit_dir(tmp, map_dir(job, task.split.index))

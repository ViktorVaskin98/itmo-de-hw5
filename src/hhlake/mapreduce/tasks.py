import json
import os
import pickle
import shutil
import time
import zlib
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

from hhlake.mapreduce.splits import Split

Key = tuple[str, ...]
SEP = "\x1f"


@dataclass(frozen=True)
class JobSpec:
    bucket: str
    key: str
    size: int
    columns: dict[str, int]
    workdir: str
    reducers: int
    combiner: bool = True
    prefilter: bool = True
    fmt: str = "csv"
    stack_sizes: tuple[int, ...] = (1, 2, 3)


@dataclass(frozen=True)
class MapTask:
    job: JobSpec
    split: Split
    attempt: int
    crash: str | None = None


@dataclass(frozen=True)
class ReduceTask:
    job: JobSpec
    partition: int
    output_prefix: str
    attempt: int = 1
    crash: bool = False


@dataclass
class MapStats:
    split: int
    attempt: int
    bytes_fetched: int = 0
    cpu_seconds: float = 0.0
    lines: int = 0
    parsed: int = 0
    in_variant: int = 0
    with_skills: int = 0
    emitted: dict[int, int] = field(default_factory=dict)
    written: dict[int, int] = field(default_factory=dict)


def partition_of(key: Key, reducers: int) -> int:
    return zlib.crc32(SEP.join(key).encode()) % reducers


def map_dir(job: JobSpec, split: int) -> Path:
    return Path(job.workdir) / "map" / f"m{split:04d}"


def map_tmp_dir(job: JobSpec, split: int, attempt: int) -> Path:
    return Path(job.workdir) / "map" / f"m{split:04d}.attempt{attempt}.tmp"


def commit_dir(tmp: Path, final: Path, attempts: int = 10) -> None:
    if final.exists():
        shutil.rmtree(tmp, ignore_errors=True)
        return
    for i in range(attempts):
        try:
            os.replace(tmp, final)
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(0.05 * (i + 1))


def write_partitions(out: Path, size: int, parts: list[Counter[Key]] | list[list[Key]]) -> None:
    for r, data in enumerate(parts):
        path = out / f"k{size}-r{r:03d}"
        if isinstance(data, Counter):
            path.with_suffix(".pkl").write_bytes(pickle.dumps(dict(data), protocol=pickle.HIGHEST_PROTOCOL))
        else:
            with path.with_suffix(".txt").open("w", encoding="utf-8") as f:
                f.writelines(f"{SEP.join(key)}\t1\n" for key in data)


def write_stats(out: Path, stats: MapStats) -> None:
    (out / "stats.json").write_text(json.dumps(asdict(stats)), encoding="utf-8")

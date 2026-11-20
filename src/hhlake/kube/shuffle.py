import json
import os
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from botocore.client import BaseClient
from botocore.exceptions import ClientError

from hhlake.mapreduce.master import _read_header
from hhlake.mapreduce.splits import Split, plan_splits
from hhlake.mapreduce.tasks import JobSpec
from hhlake.s3 import make_client
from hhlake.settings import BUCKET, RAW_KEY

MARKER = "_SUCCESS"
THREADS = 8


@dataclass(frozen=True)
class Run:
    run_id: str
    chunk_mb: int
    reducers: int
    workdir: Path
    bucket: str = BUCKET
    key: str = RAW_KEY

    @property
    def shuffle(self) -> str:
        return f"shuffle/{self.run_id}"

    @property
    def output(self) -> str:
        return f"results/k8s/{self.run_id}"

    def map_prefix(self, split: int) -> str:
        return f"{self.shuffle}/m{split:04d}"

    def reduce_prefix(self, partition: int) -> str:
        return f"{self.shuffle}/r{partition:03d}"


def plan(run: Run, s3: BaseClient | None = None) -> tuple[JobSpec, list[Split]]:
    s3 = s3 or make_client()
    size = s3.head_object(Bucket=run.bucket, Key=run.key)["ContentLength"]
    columns = _read_header(run.bucket, run.key)
    job = JobSpec(run.bucket, run.key, size, columns, str(run.workdir / run.run_id), run.reducers)
    return job, plan_splits(size, run.chunk_mb << 20)


def completion_index() -> int:
    raw = os.environ.get("JOB_COMPLETION_INDEX")
    if raw is None:
        raise SystemExit("JOB_COMPLETION_INDEX is not set: run this as an Indexed Job")
    return int(raw)


def exists(s3: BaseClient, bucket: str, key: str) -> bool:
    try:
        s3.head_object(Bucket=bucket, Key=key)
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
            return False
        raise
    return True


def list_keys(s3: BaseClient, bucket: str, prefix: str) -> list[str]:
    keys: list[str] = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        keys.extend(obj["Key"] for obj in page.get("Contents", []))
    return keys


def parallel(fn: Callable[[str], int], items: Iterable[str]) -> int:
    with ThreadPoolExecutor(THREADS) as pool:
        return sum(pool.map(fn, items))


def upload_dir(s3: BaseClient, bucket: str, local: Path, prefix: str) -> int:
    def put(name: str) -> int:
        body = (local / name).read_bytes()
        s3.put_object(Bucket=bucket, Key=f"{prefix}/{name}", Body=body)
        return len(body)

    return parallel(put, sorted(p.name for p in local.iterdir() if p.is_file()))


def download(s3: BaseClient, bucket: str, keys: list[str], dest: Callable[[str], Path]) -> int:
    def get(key: str) -> int:
        body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        path = dest(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return len(body)

    return parallel(get, keys)


def read_json(s3: BaseClient, bucket: str, key: str) -> dict:
    return json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read())

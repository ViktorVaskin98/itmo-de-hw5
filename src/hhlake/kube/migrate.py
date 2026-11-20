import argparse
import hashlib
import os
import sys
import time
from dataclasses import replace

from boto3.s3.transfer import TransferConfig
from botocore.client import BaseClient

from hhlake.kube.shuffle import list_keys
from hhlake.s3 import make_client
from hhlake.settings import BUCKET, RAW_KEY, S3Settings

PART = 16 << 20
MIB = 1 << 20


class HashingReader:
    def __init__(self, body: object) -> None:
        self.body = body
        self.md5 = hashlib.md5()
        self.read_bytes = 0

    def read(self, size: int = -1) -> bytes:
        chunk = self.body.read(size)  # type: ignore[attr-defined]
        self.md5.update(chunk)
        self.read_bytes += len(chunk)
        return chunk


def md5_of(s3: BaseClient, bucket: str, key: str) -> str:
    h = hashlib.md5()
    for chunk in s3.get_object(Bucket=bucket, Key=key)["Body"].iter_chunks(PART):
        h.update(chunk)
    return h.hexdigest()


def copy(src: BaseClient, dst: BaseClient, key: str, target_key: str) -> tuple[int, str, str, float]:
    t0 = time.perf_counter()
    reader = HashingReader(src.get_object(Bucket=BUCKET, Key=key)["Body"])
    config = TransferConfig(multipart_threshold=PART, multipart_chunksize=PART, max_concurrency=4)
    dst.upload_fileobj(reader, BUCKET, target_key, Config=config)
    elapsed = time.perf_counter() - t0
    return reader.read_bytes, reader.md5.hexdigest(), md5_of(dst, BUCKET, target_key), elapsed


def ensure_bucket(s3: BaseClient) -> None:
    existing = {b["Name"] for b in s3.list_buckets().get("Buckets", [])}
    if BUCKET not in existing:
        s3.create_bucket(Bucket=BUCKET)
        print(f"created bucket {BUCKET}")


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m hhlake.kube.migrate")
    p.add_argument("--source", default=os.environ.get("SOURCE_S3_ENDPOINT", "http://rustfs-lab:9000"))
    p.add_argument("--reference", default="results/mapreduce", help="HW3 MapReduce output in the source bucket")
    p.add_argument("--reference-target", default="results/hw3/mapreduce")
    a = p.parse_args()
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[union-attr]

    target = S3Settings()
    src = make_client(replace(target, endpoint=a.source))
    dst = make_client(target)
    print(f"source {a.source}  ->  target {target.endpoint}")
    ensure_bucket(dst)

    plan = [(RAW_KEY, RAW_KEY)]
    plan += [(k, a.reference_target + k[len(a.reference) :]) for k in list_keys(src, BUCKET, a.reference + "/")]
    ok = True
    for key, target_key in plan:
        size, md5_src, md5_dst, elapsed = copy(src, dst, key, target_key)
        same = md5_src == md5_dst
        ok &= same
        speed = f"{size / MIB / elapsed:6.1f} MiB/s" if size > PART else ""
        print(
            f"{'OK ' if same else 'BAD'} {key} -> {target_key}: {size:>11,} B  md5 {md5_src[:12]}.. / {md5_dst[:12]}.. "
            f"{elapsed:6.2f} s {speed}"
        )
    head = dst.head_object(Bucket=BUCKET, Key=RAW_KEY)
    print(f"target s3://{BUCKET}/{RAW_KEY}: {head['ContentLength']:,} bytes, ETag {head['ETag']}")
    print(f"copied {len(plan)} objects, checksums {'match' if ok else 'DIFFER'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

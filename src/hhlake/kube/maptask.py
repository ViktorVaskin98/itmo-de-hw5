import argparse
import os
import sys
import time
from pathlib import Path

from hhlake.kube.shuffle import MARKER, Run, completion_index, exists, plan, upload_dir
from hhlake.mapreduce.mapper import run_map
from hhlake.mapreduce.tasks import MapTask, map_dir
from hhlake.s3 import make_client


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m hhlake.kube.maptask")
    p.add_argument("--run", required=True)
    p.add_argument("--chunk-mb", type=int, default=32)
    p.add_argument("--reducers", type=int, default=4)
    p.add_argument("--workdir", type=Path, default=Path("/work"))
    a = p.parse_args()
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[union-attr]

    t0 = time.perf_counter()
    pod = os.environ.get("HOSTNAME", "local")
    run = Run(a.run, a.chunk_mb, a.reducers, a.workdir)
    s3 = make_client()
    job, splits = plan(run, s3)
    index = completion_index()
    if index >= len(splits):
        raise SystemExit(f"index {index} out of range: the object has {len(splits)} splits of {a.chunk_mb} MiB")
    split = splits[index]
    prefix = run.map_prefix(index)
    tag = f"[map m{index:04d} {pod}]"
    if exists(s3, run.bucket, f"{prefix}/{MARKER}"):
        print(f"{tag} already committed by an earlier pod, nothing to do")
        return

    print(f"{tag} split {index + 1}/{len(splits)}: bytes {split.start:,}-{split.end:,} of s3://{run.bucket}/{run.key}")
    run_map(MapTask(job, split, 1))
    local = map_dir(job, index)
    uploaded = upload_dir(s3, run.bucket, local, prefix)
    s3.put_object(Bucket=run.bucket, Key=f"{prefix}/{MARKER}", Body=pod.encode())
    stats = (local / "stats.json").read_text(encoding="utf-8")
    print(f"{tag} stats {stats}")
    print(f"{tag} uploaded {uploaded:,} bytes to s3://{run.bucket}/{prefix}/ in {time.perf_counter() - t0:.2f} s")


if __name__ == "__main__":
    main()

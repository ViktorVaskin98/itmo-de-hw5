import argparse
import json
import os
import sys
import time
from pathlib import Path

from hhlake.kube.shuffle import MARKER, Run, completion_index, download, exists, list_keys, plan
from hhlake.mapreduce.reducer import run_reduce
from hhlake.mapreduce.tasks import ReduceTask
from hhlake.s3 import make_client


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m hhlake.kube.reducetask")
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
    partition = completion_index()
    tag = f"[reduce r{partition:03d} {pod}]"
    missing = [s.index for s in splits if not exists(s3, run.bucket, f"{run.map_prefix(s.index)}/{MARKER}")]
    if missing:
        raise SystemExit(f"{tag} map output missing for splits {missing}: run the map job first")

    suffix = f"-r{partition:03d}.pkl"
    keys = [k for k in list_keys(s3, run.bucket, f"{run.shuffle}/m") if k.endswith(suffix)]
    fetched = download(s3, run.bucket, keys, lambda k: Path(job.workdir) / "map" / Path(k).parent.name / Path(k).name)
    print(f"{tag} fetched {len(keys)} partition files from {len(splits)} splits, {fetched:,} bytes")

    run_reduce(ReduceTask(job, partition, run.output))
    summary_path = Path(job.workdir) / "reduce" / f"r{partition:03d}" / "summary.json"
    s3.put_object(Bucket=run.bucket, Key=f"{run.reduce_prefix(partition)}/summary.json", Body=summary_path.read_bytes())
    for k, part in json.loads(summary_path.read_text(encoding="utf-8")).items():
        print(f"{tag} stack {k}: {part['distinct']:,} keys, {part['total']:,} occurrences")
    elapsed = time.perf_counter() - t0
    print(f"{tag} wrote s3://{run.bucket}/{run.output}/*/part-r-{partition:05d}.csv in {elapsed:.2f} s")


if __name__ == "__main__":
    main()

import argparse
from pathlib import Path

from hhlake.kube.shuffle import Run, plan


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m hhlake.kube.plan")
    p.add_argument("--chunk-mb", type=int, default=32)
    p.add_argument("--quiet", action="store_true", help="print only the number of splits")
    a = p.parse_args()
    job, splits = plan(Run("plan", a.chunk_mb, 1, Path("work")))
    if a.quiet:
        print(len(splits))
        return
    print(f"s3://{job.bucket}/{job.key}: {job.size:,} bytes, {len(splits)} splits x {a.chunk_mb} MiB")
    for s in splits[:2] + splits[-1:]:
        print(f"  m{s.index:04d}: bytes {s.start:,}-{s.end:,} ({s.length:,})")


if __name__ == "__main__":
    main()

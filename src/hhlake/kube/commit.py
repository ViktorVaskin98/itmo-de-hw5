import argparse
import json
import sys
from pathlib import Path

from hhlake.kube.shuffle import MARKER, Run, exists, plan, read_json
from hhlake.s3 import make_client
from hhlake.settings import STACK_NAMES

COUNTERS = ("bytes_fetched", "cpu_seconds", "lines", "parsed", "in_variant", "with_skills")


def merge_map_stats(stats: list[dict]) -> dict:
    totals: dict = dict.fromkeys(COUNTERS, 0) | {"emitted": {}, "written": {}}
    for st in stats:
        for name in COUNTERS:
            totals[name] += st[name]
        for name in ("emitted", "written"):
            for k, v in st[name].items():
                totals[name][int(k)] = totals[name].get(int(k), 0) + v
    return totals


def merge_summaries(parts: list[dict]) -> dict[int, dict]:
    merged: dict[int, dict] = {}
    for part in parts:
        for k, s in part.items():
            acc = merged.setdefault(int(k), {"distinct": 0, "total": 0, "top": []})
            acc["distinct"] += s["distinct"]
            acc["total"] += s["total"]
            acc["top"].extend(s["top"])
    for acc in merged.values():
        acc["top"] = sorted(acc["top"], key=lambda kv: (-kv[1], kv[0]))[:10]
    return merged


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m hhlake.kube.commit")
    p.add_argument("--run", required=True)
    p.add_argument("--chunk-mb", type=int, default=32)
    p.add_argument("--reducers", type=int, default=4)
    a = p.parse_args()
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[union-attr]

    run = Run(a.run, a.chunk_mb, a.reducers, Path("/work"))
    s3 = make_client()
    job, splits = plan(run, s3)
    stats = [read_json(s3, run.bucket, f"{run.map_prefix(s.index)}/stats.json") for s in splits]
    owners = [
        s3.get_object(Bucket=run.bucket, Key=f"{run.map_prefix(s.index)}/{MARKER}")["Body"].read().decode()
        for s in splits
    ]
    summaries = [read_json(s3, run.bucket, f"{run.reduce_prefix(r)}/summary.json") for r in range(run.reducers)]
    totals = merge_map_stats(stats)
    merged = merge_summaries(summaries)
    print(f"[commit] run {run.run_id}: {len(splits)} map splits by {len(set(owners))} pods, {run.reducers} reducers")
    for k, name in STACK_NAMES.items():
        emitted, reduced = totals["emitted"][k], merged[k]["total"]
        distinct = merged[k]["distinct"]
        status = "ok" if emitted == reduced else "MISMATCH"
        print(f"[commit] {name:<8} emitted {emitted:>9,}  reduced {reduced:>9,}  distinct {distinct:>7,}  {status}")
        if emitted != reduced:
            raise SystemExit(f"{name}: reduced {reduced} != emitted {emitted}, no {MARKER}")
    if exists(s3, run.bucket, f"{run.output}/{MARKER}"):
        print(f"[commit] s3://{run.bucket}/{run.output}/{MARKER} already present")
    result = {
        "input": f"s3://{run.bucket}/{run.key}",
        "output": f"s3://{run.bucket}/{run.output}",
        "size": job.size,
        "splits": len(splits),
        "chunk_mb": run.chunk_mb,
        "reducers": run.reducers,
        "map_pods": owners,
        "map": totals,
        "stacks": merged,
    }
    body = json.dumps(result, ensure_ascii=False, indent=1).encode("utf-8")
    s3.put_object(Bucket=run.bucket, Key=f"{run.output}/_job.json", Body=body)
    s3.put_object(Bucket=run.bucket, Key=f"{run.output}/{MARKER}", Body=b"")
    print(f"[commit] variant vacancies {totals['in_variant']:,}, with key_skills {totals['with_skills']:,}")
    print(f"[commit] wrote s3://{run.bucket}/{run.output}/_job.json and {MARKER}")


if __name__ == "__main__":
    main()

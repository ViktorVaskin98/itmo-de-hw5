import argparse
import json
import math
from pathlib import Path

MIB = 1 << 20
TAG = "[mem-summary] "


def summaries(paths: list[Path]) -> list[dict]:
    found = []
    for path in paths:
        files = sorted(path.glob("*.log")) if path.is_dir() else [path]
        for f in files:
            for line in f.read_text(encoding="utf-8-sig").splitlines():
                if line.startswith(TAG):
                    found.append(json.loads(line[len(TAG) :]))
    return found


def recommend(peak: int, headroom: float, step_mib: int) -> int:
    return math.ceil(peak * headroom / (step_mib * MIB)) * step_mib


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m hhlake.kube.sizing")
    p.add_argument("paths", nargs="+", type=Path, help="pod log files or directories with them")
    p.add_argument("--headroom", type=float, default=1.2)
    p.add_argument("--step-mib", type=int, default=64)
    p.add_argument("--quiet", action="store_true", help="print only the recommended limit, e.g. 704Mi")
    p.add_argument("--peak-only", action="store_true", help="print only the max memory.peak in MiB")
    p.add_argument("--anon-only", action="store_true", help="print only the max sampled anon memory in MiB")
    a = p.parse_args()

    runs = [s for s in summaries(a.paths) if s["exit"] == 0]
    if not runs:
        raise SystemExit("no successful runs with [mem-summary] found")
    peak = max(s["memory_peak"] for s in runs)
    limit = recommend(peak, a.headroom, a.step_mib)
    if a.anon_only:
        print(math.ceil(max(s["sampled"]["anon"] for s in runs) / MIB))
        return
    if a.peak_only:
        print(math.ceil(peak / MIB))
        return
    if a.quiet:
        print(f"{limit}Mi")
        return
    header = ("pod", "limit", "wall, s", "memory.peak", "anon", "file", "CPU, s", "throttled")
    widths = (26, 8, 9, 13, 7, 7, 8, 11)
    print(f"{header[0]:<{widths[0]}}" + "".join(f"{h:>{w}}" for h, w in zip(header[1:], widths[1:], strict=True)))
    for s in sorted(runs, key=lambda s: s["pod"]):
        print(
            f"{s['pod']:<26}{s['memory_max'] // MIB:>6}Mi{s['wall']:>9.1f}{s['memory_peak'] / MIB:>9.0f} MiB"
            f"{s['sampled']['anon'] / MIB:>7.0f}{s['sampled']['file'] / MIB:>7.0f}{s['cpu_usage']:>8.1f}"
            f"{s['cpu_throttled']:>9.1f} s"
        )
    peaks = sorted(s["memory_peak"] / MIB for s in runs)
    median = peaks[len(peaks) // 2]
    print(f"runs {len(runs)}, memory.peak min {peaks[0]:.0f} / median {median:.0f} / max {peaks[-1]:.0f} MiB")
    print(
        f"limit = ceil(max peak {peak / MIB:.0f} MiB x {a.headroom} / {a.step_mib} MiB) x {a.step_mib} MiB = {limit}Mi"
    )


if __name__ == "__main__":
    main()

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


def ts(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


@dataclass
class PodSpan:
    name: str
    run: str
    stage: str
    index: str
    node: str
    priority: str
    created: datetime
    scheduled: datetime | None
    started: datetime | None
    finished: datetime | None
    result: str

    @property
    def pending(self) -> float:
        end = self.scheduled or self.finished or self.created
        return (end - self.created).total_seconds()


def _condition(pod: dict, kind: str) -> dict | None:
    for c in pod["status"].get("conditions", []):
        if c["type"] == kind and c["status"] == "True":
            return c
    return None


def load(dirs: list[Path]) -> list[PodSpan]:
    spans = []
    for d in dirs:
        items = json.loads((d / "pods.json").read_text(encoding="utf-8-sig"))["items"]
        for pod in items:
            meta, status = pod["metadata"], pod["status"]
            scheduled = _condition(pod, "PodScheduled")
            disrupted = _condition(pod, "DisruptionTarget")
            cs = (status.get("containerStatuses") or [{}])[0].get("state", {})
            term, running = cs.get("terminated"), cs.get("running")
            if disrupted:
                result = "preempted" if disrupted.get("reason") == "PreemptionByScheduler" else disrupted.get("reason")
            elif term:
                result = term.get("reason", "?")
            else:
                result = status.get("phase", "?")
            started = ts((term or running or {}).get("startedAt"))
            finished = ts(term.get("finishedAt")) if term else None
            if disrupted and not finished:
                finished = ts(disrupted["lastTransitionTime"])
            spans.append(
                PodSpan(
                    meta["name"],
                    meta["labels"].get("hw5/run", "?"),
                    meta["labels"].get("hw5/stage", "?"),
                    meta.get("annotations", {}).get("batch.kubernetes.io/job-completion-index", ""),
                    pod["spec"].get("nodeName", "-"),
                    pod["spec"].get("priorityClassName", ""),
                    ts(meta["creationTimestamp"]),  # type: ignore[arg-type]
                    ts(scheduled["lastTransitionTime"]) if scheduled else None,
                    started,
                    finished,
                    result,
                )
            )
    return sorted(spans, key=lambda s: (s.created, s.name))


def max_concurrent(spans: list[PodSpan]) -> int:
    points = []
    for s in spans:
        if s.started and s.finished:
            points += [(s.started, 1), (s.finished, -1)]
    best = cur = 0
    for _, d in sorted(points, key=lambda p: (p[0], p[1])):
        cur += d
        best = max(best, cur)
    return best


def rel(t: datetime | None, t0: datetime) -> str:
    return f"{(t - t0).total_seconds():6.0f}" if t else "     -"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("dirs", nargs="+", type=Path)
    p.add_argument("--brief", action="store_true")
    a = p.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    spans = load(a.dirs)
    t0 = min(s.created for s in spans)
    if not a.brief:
        print(f"times in seconds from {t0:%H:%M:%S} UTC: created, scheduled, started, finished")
        print(f"{'pod':<24}{'node':<13}{'created':>8}{'sched':>7}{'start':>7}{'end':>7}{'pending':>9}  result")
        for s in spans:
            print(
                f"{s.name:<24}{s.node:<13}{rel(s.created, t0):>8}{rel(s.scheduled, t0):>7}{rel(s.started, t0):>7}"
                f"{rel(s.finished, t0):>7}{s.pending:>8.0f}s  {s.result}"
            )
    for (run, stage), group in sorted(_groups(spans).items(), key=lambda kv: min(s.created for s in kv[1])):
        done = [s.finished for s in group if s.finished]
        span = (max(done) - min(s.created for s in group)).total_seconds() if done else float("nan")
        waits = [s.pending for s in group]
        mean_wait = sum(waits) / len(waits)
        nodes = sorted({s.node for s in group})
        preempted = sum(s.result == "preempted" for s in group)
        print(
            f"{run}/{stage}: {len(group)} pods ({preempted} preempted), {span:.0f} s from first create to last finish, "
            f"max {max_concurrent(group)} running at once, pending max {max(waits):.0f} s / mean {mean_wait:.1f} s, "
            f"nodes {', '.join(nodes)}"
        )


def _groups(spans: list[PodSpan]) -> dict[tuple[str, str], list[PodSpan]]:
    out: dict[tuple[str, str], list[PodSpan]] = {}
    for s in spans:
        out.setdefault((s.run, s.stage), []).append(s)
    return out


if __name__ == "__main__":
    main()

import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import Patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from timeline import PodSpan, load  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / "logs"
FIGS = ROOT / "report" / "figs"
BLUE, ORANGE, AQUA, RED, VIOLET = "#2a78d6", "#eb6834", "#1baf7a", "#c8372d", "#7b5cc4"
INK, INK2, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#8a8984", "#e6e5e1", "#fcfcfb"
MIB = 1 << 20

plt.rcParams.update(
    {
        "font.family": "Calibri",
        "font.size": 9,
        "axes.edgecolor": MUTED,
        "axes.labelcolor": INK2,
        "xtick.color": INK2,
        "ytick.color": INK2,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
        "hatch.linewidth": 0.6,
    }
)

STAGE_COLOR = {"map": BLUE, "reduce": AQUA, "commit": VIOLET, "hw3-job": ORANGE, "verify": VIOLET}


def mem_series(run: str) -> tuple[list[float], list[float], int | None]:
    log = next((LOGS / "pods" / "hw3" / run).glob("*.log"))
    xs, ys, limit = [], [], None
    for line in log.read_text(encoding="utf-8-sig").splitlines():
        if line.startswith("[mem-json] "):
            d = json.loads(line[11:])
            xs.append(d["t"])
            ys.append(d["current"] / MIB)
        elif line.startswith("[mem] pod ") and "memory.max" in line:
            limit = int(line.split("memory.max ")[1].split(" MiB")[0])
    return xs, ys, limit


def fig_memory() -> None:
    fig, ax = plt.subplots(figsize=(7.2, 2.9))
    runs = [
        ("hw3-measure-1", BLUE, "замер, предел 2Gi"),
        ("hw3-tuned-1", AQUA, "подобранный предел"),
        ("hw3-below", RED, "ниже пика anon"),
        ("hw3-256mi", ORANGE, "256Mi"),
    ]
    for run, color, label in runs:
        xs, ys, limit = mem_series(run)
        ax.plot(xs, ys, color=color, lw=1.6, marker="o", ms=2.5, label=f"{label}")
        if limit and limit < 2048:
            ax.axhline(limit, color=color, lw=0.9, ls=(0, (4, 3)))
            ax.text(xs[-1] if run != "hw3-tuned-1" else 1, limit + 8, f"limit {limit} MiB", color=color, fontsize=7.5)
        if run in ("hw3-256mi", "hw3-below"):
            ax.plot(xs[-1], ys[-1], marker="X", color=RED, ms=8)
    ax.set_xlabel("секунды от старта контейнера")
    ax.set_ylabel("memory.current, MiB")
    ax.grid(axis="y", color=GRID, lw=0.6)
    ax.set_ylim(0, None)
    ax.legend(frameon=False, fontsize=8, loc="lower right", ncol=2)
    fig.tight_layout()
    fig.savefig(FIGS / "memory.png", dpi=220)
    plt.close(fig)


def gantt(dirs: list[str], out: str, title: str, height: float | None = None) -> None:
    spans = load([LOGS / "state" / "runs" / d for d in dirs])
    t0 = min(s.created for s in spans)
    n = len(spans)
    fig, ax = plt.subplots(figsize=(7.2, height or max(2.2, 0.13 * n + 0.9)))

    def x(t: object) -> float:
        return (t - t0).total_seconds()  # type: ignore[operator]

    for i, s in enumerate(spans):
        y = n - 1 - i
        end = s.finished or s.created
        sched = s.scheduled or end
        if x(sched) - x(s.created) > 0.3:
            ax.barh(y, x(sched) - x(s.created), left=x(s.created), height=0.62, color="#d9d7d0", edgecolor="none")
        start = s.started or sched
        if x(start) > x(sched):
            ax.barh(y, x(start) - x(sched), left=x(sched), height=0.62, color="#b9c7d6", edgecolor="none")
        color = STAGE_COLOR.get(s.stage, MUTED)
        if s.priority == "batch-high":
            color = ORANGE
        if s.finished and s.started:
            hatch = "////" if s.result == "preempted" else None
            face = SURFACE if s.result == "preempted" else color
            ax.barh(
                y,
                x(s.finished) - x(s.started),
                left=x(s.started),
                height=0.62,
                color=face,
                edgecolor=RED if s.result == "preempted" else "none",
                hatch=hatch,
                lw=0.8,
            )
        if s.result == "preempted":
            ax.plot(x(s.finished), y, marker="X", color=RED, ms=5)
    ax.set_yticks(range(n))
    ax.set_yticklabels([_short(s) for s in reversed(spans)], fontsize=5.6 if n > 30 else 6.5)
    ax.set_xlabel("секунды от создания первого пода")
    ax.grid(axis="x", color=GRID, lw=0.6)
    ax.set_ylim(-0.6, n - 0.4)
    stages = sorted({s.stage for s in spans}, key=list(STAGE_COLOR).index)
    handles = [
        Patch(color="#d9d7d0", label="Pending (ждёт узел)"),
        Patch(color="#b9c7d6", label="назначен, старт контейнера"),
    ]
    handles += [Patch(color=STAGE_COLOR[st], label=st) for st in stages if st != "hw3-job"]
    if any(s.priority == "batch-high" for s in spans):
        handles.append(Patch(color=ORANGE, label="batch-high: расчёт ДЗ 3"))
    if any(s.result == "preempted" for s in spans):
        handles.append(Patch(facecolor=SURFACE, edgecolor=RED, hatch="////", label="вытеснен"))
    ax.legend(
        handles=handles,
        frameon=False,
        fontsize=7,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.11 - 2.2 / (n + 8)),
        ncol=min(len(handles), 4),
    )
    ax.set_title(title, fontsize=9, color=INK2, loc="left")
    fig.tight_layout()
    fig.savefig(FIGS / out, dpi=220)
    plt.close(fig)


def _short(s: PodSpan) -> str:
    idx = f"-{s.index}" if s.index else ""
    node = s.node.replace("hw5-", "") if s.node else "-"
    return f"{s.run}-{s.stage}{idx} ({node})"


def main() -> None:
    FIGS.mkdir(parents=True, exist_ok=True)
    fig_memory()
    gantt(["par"], "gantt_par.png", "map 26 x 1 CPU, parallelism 8; reduce 4; commit")
    gantt(["cpu"], "gantt_cpu.png", "map 26 x 1500m CPU, parallelism 8: на воркер помещается два пода")
    gantt(["low", "urgent"], "gantt_preempt.png", "low (batch-low) и urgent (batch-high, 2 CPU)")
    gantt(["quota"], "gantt_quota.png", "пространство hw5-quota: requests.cpu 3")


if __name__ == "__main__":
    main()

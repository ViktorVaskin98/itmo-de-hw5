import json
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from logrender import Block, blocks, find, render_block, write_snippet  # noqa: E402
from timeline import PodSpan, load, max_concurrent  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / "logs"
OUT = ROOT / "report" / "snippets"
MIB = 1 << 20


def snippet(name: str, items: list[tuple[Block, dict]]) -> None:
    write_snippet(OUT / f"{name}.txt", "\n\n".join(render_block(b, **opts) for b, opts in items))


def pick(log: str, pattern: str, nth: int = 0, **opts: object) -> tuple[Block, dict]:
    return find(LOGS / log, pattern, nth), opts


def trimmed(log: str, pattern: str, keep: str, nth: int = 0) -> tuple[Block, dict]:
    b = find(LOGS / log, pattern, nth)
    return Block(b.command, [line for line in b.output if re.search(keep, line)]), {}


def cut(log: str, pattern: str, width: int, nth: int = 0, **opts: object) -> tuple[Block, dict]:
    b = find(LOGS / log, pattern, nth)
    return Block(b.command, [line if len(line) <= width else line[: width - 3] + "..." for line in b.output]), opts


def build_snippets() -> None:
    snippet(
        "cluster",
        [
            pick("01_cluster.txt", r"Get-FileHash"),
            pick("01_cluster.txt", r"Win32_ComputerSystem"),
            pick("01_cluster.txt", r"kind version"),
            pick("01_cluster.txt", r"docker info"),
            pick("01_cluster.txt", r"kind create cluster", head_tail=(2, 3)),
            pick("01_cluster.txt", r"custom-columns=NODE"),
        ],
    )
    snippet(
        "cluster_net",
        [
            pick("01_cluster.txt", r"docker network connect"),
            pick("01_cluster.txt", r"kc run dnscheck"),
            pick("01_cluster.txt", r"kc logs dnscheck"),
        ],
    )
    snippet(
        "image",
        [
            pick("02_image.txt", r"docker image ls"),
            pick("02_image.txt", r"du -sh"),
            pick("02_image.txt", r"docker run --rm \$Image sh -c \"id"),
            pick("02_image.txt", r"kind load"),
            pick("02_image.txt", r"crictl images"),
        ],
    )
    snippet(
        "oom",
        [
            pick("03_memory.txt", r"Run-Hw3 \"hw3-256mi\""),
            pick("03_memory.txt", r"Show-Job hw5 hw3-256mi"),
            pick("03_memory.txt", r"get pods -l hw5/run=hw3-256mi"),
            pick("03_memory.txt", r"Show-Log hw5 job/hw3-256mi"),
        ],
    )
    snippet(
        "oom_kernel",
        [cut("03_memory.txt", r"Kernel-Oom \$oomNode \"hw3-256mi\"", 172, head_tail=(6, 3))],
    )
    snippet("tuned_verify", [pick("03_memory.txt", r"verify --a results/k8s/hw3-tuned-1")])
    snippet(
        "measure",
        [
            pick("03_memory.txt", r"Run-Hw3 hw3-measure-1"),
            pick("03_memory.txt", r"sizing logs\\pods\\hw3\\hw3-measure"),
        ],
    )
    snippet(
        "measure_log",
        [pick("03_memory.txt", r"Show-Log hw5 job/hw3-measure-1", head_tail=(9, 6))],
    )
    snippet(
        "tuned",
        [
            pick("03_memory.txt", r"get jobs -l hw5/stage=hw3-job"),
            pick("03_memory.txt", r"sizing logs\\pods\\hw3\\hw3-tuned"),
            pick("03_memory.txt", r"Select-String -Path logs\\pods\\hw3\\hw3-tuned"),
        ],
    )
    snippet(
        "below",
        [
            pick("03_memory.txt", r"Run-Hw3 hw3-below"),
            pick("03_memory.txt", r"get pods -l hw5/run=hw3-below"),
            cut("03_memory.txt", r"Kernel-Oom \$oomNode \"hw3-below\"", 172),
        ],
    )
    snippet(
        "storage",
        [
            pick("04_storage.txt", r"rollout status"),
            pick("04_storage.txt", r"docker inspect rustfs-lab"),
            pick("04_storage.txt", r"get \"statefulset,pod,svc\""),
            pick("04_storage.txt", r"get pvc", head_tail=(3, 1)),
            pick("04_storage.txt", r"kc get pv ", head_tail=(2, 1)),
        ],
    )
    migrate = find(LOGS / "04_storage.txt", r"Show-Log hw5 job/s3-migrate")
    short = []
    for line in migrate.output:
        m = re.match(r"(OK |BAD) (\S+) -> (\S+): +([\d,]+) B +md5 (\S+) / (\S+) +([\d.]+ s)(.*)$", line)
        short.append(f"{m[1]} {m[3]:<46} {m[4]:>12} B  md5 {m[5]} / {m[6]} {m[7]}{m[8]}" if m else line)
    snippet(
        "migrate",
        [
            (Block(migrate.command, short), {"head_tail": (6, 3)}),
            pick("04_storage.txt", r"Get-FileHash"),
            pick("04_storage.txt", r"du -sh", head_tail=(9, 0)),
        ],
    )
    snippet(
        "storage_after",
        [
            pick("04_storage.txt", r"docker stop rustfs-lab"),
            pick("04_storage.txt", r"Storage-Memory"),
            pick("04_storage.txt", r"hhlake.kube.plan"),
        ],
    )
    snippet(
        "probe",
        [
            pick("05_parallel.txt", r"Complete-Run \$probe"),
            pick("05_parallel.txt", r"probe-map-\*", head_tail=(5, 2)),
            pick("05_parallel.txt", r"probe-reduce-\*"),
        ],
    )
    snippet(
        "par_run",
        [
            pick("05_parallel.txt", r"Wait-Running hw5 \"hw5/run=par\""),
            pick("05_parallel.txt", r"Non-terminated Pods"),
            pick("05_parallel.txt", r"Show-Job hw5 par-map"),
        ],
    )
    snippet(
        "par_pods",
        [
            pick("05_parallel.txt", r"par-map-7-\*"),
            pick("05_parallel.txt", r"par-reduce-0-\*"),
        ],
    )
    snippet("par_commit", [pick("05_parallel.txt", r"Show-Log hw5 job/par-commit")])
    snippet(
        "par_csv",
        [
            pick("05_parallel.txt", r"--export work"),
            pick("05_parallel.txt", r"Get-FileHash work"),
            pick("05_parallel.txt", r"Get-Content work"),
        ],
    )
    snippet(
        "cpu",
        [
            pick("06_cpu.txt", r"Pods hw5 \"hw5/run=cpu\""),
            pick("06_cpu.txt", r"reason=FailedScheduling", head_tail=(2, 0)),
            pick("06_cpu.txt", r"Allocated resources"),
        ],
    )
    snippet(
        "cpu_after",
        [
            pick("06_cpu.txt", r"Show-Job hw5 cpu-map"),
            pick("06_cpu.txt", r"timeline.py logs\\state\\runs\\cpu", head_tail=(10, 3)),
            pick("06_cpu.txt", r"--brief"),
            pick("06_cpu.txt", r"hw3-tuned-1\\\*.log"),
        ],
    )
    snippet(
        "preempt",
        [
            pick("07_preemption.txt", r"get priorityclass"),
            pick("07_preemption.txt", r"Wait-Running hw5 \"hw5/run=low\""),
            pick("07_preemption.txt", r"Submit \"10-hw3-job.yaml\""),
            pick("07_preemption.txt", r"Watch-Disruption"),
            pick("07_preemption.txt", r"reason=Preempted"),
        ],
    )
    victim_logs = []
    for f in sorted((LOGS / "pods" / "runs" / "low").glob("low-map-*.log")):
        lines = f.read_text(encoding="utf-8-sig").splitlines()
        if any("got signal" in ln for ln in lines):
            keep = [ln for ln in lines if not ln.startswith(("[mem-json]", "[mem] ", "  ", "Traceback", "File"))]
            keep += [ln for ln in lines if ln.startswith(("[mem] got signal", "[mem] exit code"))]
            victim_logs.append((Block([f"Get-Content logs\\pods\\runs\\low\\{f.name}"], keep), {}))
    snippet("preempt_victim", victim_logs[:1])
    snippet(
        "preempt_after",
        [
            pick("07_preemption.txt", r"Show-Job hw5 low-map"),
            pick("07_preemption.txt", r"timeline.py logs\\state\\runs\\low", head_tail=(12, 4)),
            trimmed("07_preemption.txt", r"Show-Log hw5 job/urgent-verify", r"RESULT|identical|MATCH"),
            trimmed("07_preemption.txt", r"Show-Log hw5 job/low-commit", r"RESULT|identical|MATCH"),
        ],
    )
    snippet(
        "quota_admission",
        [
            pick("08_quota.txt", r"kc apply -f k8s\\40-quota"),
            pick("08_quota.txt", r"run bare", 0),
            pick("08_quota.txt", r"41-limitrange"),
            pick("08_quota.txt", r"run bare", 1),
            pick("08_quota.txt", r"get pod bare"),
        ],
    )
    snippet(
        "quota_run",
        [
            pick("08_quota.txt", r"Pods hw5-quota"),
            pick("08_quota.txt", r"describe resourcequota", 1),
            pick("08_quota.txt", r"reason=FailedCreate", head_tail=(2, 0)),
            pick("08_quota.txt", r"foreach \(\$n in \"hw5-worker\""),
        ],
    )
    snippet(
        "quota_after",
        [
            pick("08_quota.txt", r"Show-Job hw5-quota"),
            pick("08_quota.txt", r"timeline.py logs\\state\\runs\\quota", head_tail=(9, 3)),
            trimmed("08_quota.txt", r"Show-Log hw5-quota job/quota-commit", r"RESULT|identical|MATCH"),
        ],
    )
    storage = [pick(f"0{i}_{n}.txt", r"Storage-Memory") for i, n in ((4, "storage"), (5, "parallel"), (6, "cpu"))]
    storage += [pick("07_preemption.txt", r"Storage-Memory"), pick("08_quota.txt", r"Storage-Memory")]
    snippet("storage_memory", storage)
    snippet(
        "discarded",
        [
            (Block(["kc -n hw5 get pod rustfs-0 ...   # после 05_parallel"], _rustfs_states()), {}),
            (Block(["Get-Content logs\\discarded\\run1\\pods\\par-map-21-mbsm2.log | Select-Object -Last 8"], _tail(
                LOGS / "discarded" / "run1" / "pods" / "par-map-21-mbsm2.log", 4)), {}),
        ],
    )


def _rustfs_states() -> list[str]:
    text = (LOGS / "discarded" / "run1" / "rustfs_events.txt").read_text(encoding="utf-8")
    return [line for line in text.splitlines() if re.match(r"^(RESTARTS|\d+ +OOMKilled)", line)]


def _tail(path: Path, n: int) -> list[str]:
    lines = [ln for ln in path.read_text(encoding="utf-8-sig").splitlines() if not ln.startswith("[mem-json]")]
    out = []
    for ln in lines:
        if "IncompleteReadError" in ln and ln.startswith("botocore"):
            out.append(ln)
    return out + [ln for ln in lines if ln.startswith(("[mem] exit", "[mem] memory.events"))][:n]


def mem_summaries(run_dir: Path) -> list[dict]:
    found = []
    for f in sorted(run_dir.glob("*.log")):
        for line in f.read_text(encoding="utf-8-sig").splitlines():
            if line.startswith("[mem-summary] "):
                found.append(json.loads(line[14:]))
    return found


def fmt(x: float, digits: int = 0) -> str:
    s = f"{x:,.{digits}f}".replace(",", "\\,").replace(".", "{,}")
    return s


def spans(*names: str) -> list[PodSpan]:
    return load([LOGS / "state" / "runs" / n for n in names])


def stage(spans_: list[PodSpan], stage_: str) -> list[PodSpan]:
    return [s for s in spans_ if s.stage == stage_]


def span_seconds(group: list[PodSpan]) -> float:
    return (max(s.finished for s in group if s.finished) - min(s.created for s in group)).total_seconds()


def values() -> dict[str, str]:
    v: dict[str, str] = {}
    hw3 = LOGS / "pods" / "hw3"
    measure = [m for i in (1, 2, 3) for m in mem_summaries(hw3 / f"hw3-measure-{i}")]
    tuned = [m for i in (1, 2, 3) for m in mem_summaries(hw3 / f"hw3-tuned-{i}")]
    peaks = [m["memory_peak"] / MIB for m in measure]
    v["measPeakMin"], v["measPeakMax"] = fmt(min(peaks)), fmt(max(peaks))
    v["measAnonMax"] = fmt(max(m["sampled"]["anon"] for m in measure) / MIB)
    v["measFileMax"] = fmt(max(m["sampled"]["file"] for m in measure) / MIB)
    limit = (LOGS / "hw3_limit.txt").read_text(encoding="utf-8-sig").strip()
    v["hwLimit"] = limit.removesuffix("Mi")
    v["hwLimitRaw"] = fmt(max(peaks) * 1.2)
    v["tunedPeakMax"] = fmt(max(m["memory_peak"] for m in tuned) / MIB)
    v["tunedHeadroom"] = fmt(int(v["hwLimit"]) - max(m["memory_peak"] for m in tuned) / MIB)
    v["tunedWallMed"] = fmt(statistics.median(m["wall"] for m in tuned), 1)
    thr = [m["cpu_throttled"] for m in tuned]
    v["hwThrottledMin"], v["hwThrottledMax"] = fmt(min(thr), 1), fmt(max(thr), 1)
    cleared = []
    for f in hw3.glob("hw3-*/*.log"):
        m = re.search(r"cleared (\d+) old objects .*\(([\d.]+) s\)", f.read_text(encoding="utf-8-sig"))
        if m and f.parent.name not in ("hw3-256mi", "hw3-below"):
            cleared.append(float(m[2]))
    v["clearMin"], v["clearMax"] = fmt(min(cleared)), fmt(max(cleared))
    periods = []
    for i in (1, 2, 3):
        for f in (hw3 / f"hw3-tuned-{i}").glob("*.log"):
            m = re.search(r"in (\d+) of (\d+) periods", f.read_text(encoding="utf-8-sig"))
            if m:
                periods.append(f"{m[1]} из {m[2]}")
    v["hwThrPeriods"] = ", ".join(periods)
    below = re.search(r"Run-Hw3 hw3-below (\d+)Mi", (LOGS / "03_memory.txt").read_text(encoding="utf-8-sig"))
    v["belowLimit"] = below[1] if below else "?"
    oom = spans_hw3("hw3-256mi")
    v["oomSeconds"] = fmt(oom, 0)

    limits = json.loads((LOGS / "run_limits.json").read_text(encoding="utf-8-sig"))
    v["mapLimit"], v["reduceLimit"] = limits["MEMORY"].removesuffix("Mi"), limits["REDUCE_MEMORY"].removesuffix("Mi")
    v["splits"] = str(limits["SPLITS"])
    probe = LOGS / "pods" / "runs" / "probe"
    maps = [m for m in mem_summaries(probe) if m["pod"].startswith("probe-map")]
    reds = [m for m in mem_summaries(probe) if m["pod"].startswith("probe-reduce")]
    v["mapPeakMax"] = fmt(max(m["memory_peak"] for m in maps) / MIB)
    v["mapPeakMed"] = fmt(statistics.median(m["memory_peak"] for m in maps) / MIB)
    v["reducePeakMax"] = fmt(max(m["memory_peak"] for m in reds) / MIB)

    par = spans("par")
    pmap = stage(par, "map")
    v["parMapSpan"] = fmt(span_seconds(pmap))
    v["parTotal"] = fmt(span_seconds(par))
    v["parMaxRun"] = str(max_concurrent(pmap))
    nodes = sorted({s.node for s in pmap})
    v["parNodeSplit"] = " и ".join(f"{sum(s.node == n for s in pmap)}" for n in nodes)
    lags = [(s.started - s.scheduled).total_seconds() for s in pmap if s.started and s.scheduled]
    v["parStartLag"] = fmt(statistics.mean(lags), 1)
    runs = [(s.finished - s.started).total_seconds() for s in pmap if s.finished and s.started]
    v["parTaskMed"] = fmt(statistics.median(runs), 0)
    walls = [m["wall"] for m in mem_summaries(LOGS / "pods" / "runs" / "par") if m["pod"].startswith("par-map")]
    v["parWallMed"] = fmt(statistics.median(walls), 1)

    cpu = stage(spans("cpu"), "map")
    v["cpuMapSpan"] = fmt(span_seconds(cpu))
    v["cpuMaxRun"] = str(max_concurrent(cpu))
    v["cpuPendingMax"] = fmt(max(s.pending for s in cpu))
    v["cpuPendingMean"] = fmt(statistics.mean(s.pending for s in cpu), 1)
    v["cpuPendingCount"] = str(sum(s.pending >= 1 for s in cpu))

    uploads, plans = [], []
    for f in (LOGS / "pods" / "runs" / "par").glob("par-map-*.log"):
        m = re.search(r"plan ([\d.]+) s, map ([\d.]+) s, upload ([\d.]+) s", f.read_text(encoding="utf-8-sig"))
        if m:
            plans.append(float(m[1]))
            uploads.append(float(m[3]))
    v["mapUploadMed"] = fmt(statistics.median(uploads), 1)
    v["mapPlanMed"] = fmt(statistics.median(plans), 1)

    kernel = find(LOGS / "03_memory.txt", r"Kernel-Oom \$oomNode \"hw3-256mi\"").output
    v["oomKilled"] = str(sum("Killed process" in line for line in kernel))
    m = re.search(r"oom_score_adj=(\d+)", " ".join(kernel))
    v["oomScoreAdj"] = m[1] if m else "?"

    low = spans("low", "urgent")
    lmap = stage(low, "map")
    v["preemptedCount"] = str(sum(s.result == "preempted" for s in lmap))
    v["lowMapSpan"] = fmt(span_seconds(lmap))
    v["lowPods"] = str(len(lmap))
    urgent = stage(low, "hw3-job")[0]
    v["urgentPending"] = fmt(urgent.pending)
    v["urgentSpan"] = fmt((urgent.finished - urgent.created).total_seconds())  # type: ignore[operator]
    victims = [s for s in lmap if s.result == "preempted"]
    v["preemptNode"] = victims[0].node if victims else "?"
    v["preemptedIdx"] = " и ".join(sorted((s.index for s in victims), key=int))
    v["preemptedRan"] = fmt(statistics.mean((s.finished - s.started).total_seconds() for s in victims))  # type: ignore[operator]
    survivors = [s for s in lmap if s.result != "preempted" and s.started and s.finished]
    v["lowTaskMed"] = fmt(statistics.median((s.finished - s.started).total_seconds() for s in survivors))  # type: ignore[operator]
    urgent_mem = mem_summaries(LOGS / "pods" / "runs" / "urgent")
    v["urgentWall"] = fmt(urgent_mem[0]["wall"], 1)

    quota = stage(spans("quota"), "map")
    v["quotaMaxRun"] = str(max_concurrent(quota))
    v["quotaMapSpan"] = fmt(span_seconds(quota))
    events = json.loads((LOGS / "state" / "runs" / "quota" / "events.json").read_text(encoding="utf-8-sig"))["items"]
    v["quotaFailedCreate"] = str(sum(e.get("count", 1) for e in events if e["reason"] == "FailedCreate"))
    used = find(LOGS / "08_quota.txt", r"foreach \(\$n in \"hw5-worker\"").output
    reqs = [int(m[1]) for line in used if (m := re.match(r"cpu\s+(\d+)m", line.strip()))]
    reqs += [int(m[1]) * 1000 for line in used if (m := re.match(r"cpu\s+(\d+)\s+\(", line.strip()))]
    v["quotaFreeCpu"] = fmt((2 * 3900 + 200 - sum(reqs)) / 1000, 1)

    rfs = []
    for log in ("04_storage", "05_parallel", "06_cpu", "07_preemption", "08_quota"):
        b = find(LOGS / f"{log}.txt", r"Storage-Memory")
        m = re.search(r"anon (\d+) MiB, memory.peak (\d+) MiB", b.output[0])
        rfs.append((int(m[1]), int(m[2])))  # type: ignore[index]
    v["rfsAnonStart"], v["rfsAnonEnd"] = fmt(rfs[0][0]), fmt(rfs[-1][0])
    v["rfsPeakEnd"] = fmt(max(p for _, p in rfs))
    v["rfsAnonPar"] = fmt(rfs[1][0])
    v["rfsAnonCpu"], v["rfsAnonLow"] = fmt(rfs[2][0]), fmt(rfs[3][0])
    v["rfsGrowFirst"] = fmt((rfs[1][0] - rfs[0][0]) / 2)
    v["rfsGrowLater"] = fmt((rfs[-1][0] - rfs[1][0]) / 4)

    image = find(LOGS / "02_image.txt", r"docker image ls").output[0]
    size = re.search(r"([\d.]+)(MB|GB)$", image.strip())
    v["imageSize"] = f"{size[1].replace('.', '{,}')}\\,{'МБ' if size[2] == 'MB' else 'ГБ'}"  # type: ignore[index]

    mig = (LOGS / "04_storage.txt").read_text(encoding="utf-8-sig")
    m = re.search(r"raw/it_vacancies_2024\.csv: +[\d,]+ B .*? ([\d.]+) s +([\d.]+) MiB/s", mig)
    v["migSeconds"], v["migSpeed"] = fmt(float(m[1]), 0), fmt(float(m[2]), 1)  # type: ignore[index]
    return v


def spans_hw3(run: str) -> float:
    pods = json.loads((LOGS / "state" / "hw3" / run / "pods.json").read_text(encoding="utf-8-sig"))["items"]
    term = pods[0]["status"]["containerStatuses"][0]["state"]["terminated"]
    from timeline import ts

    return (ts(term["finishedAt"]) - ts(term["startedAt"])).total_seconds()  # type: ignore[operator]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    build_snippets()
    vals = values()
    lines = [f"\\newcommand{{\\{k}}}{{{v}}}" for k, v in sorted(vals.items())]
    (OUT / "values.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for k, v in sorted(vals.items()):
        print(f"{k:<20}{v}")
    _ = blocks


if __name__ == "__main__":
    main()

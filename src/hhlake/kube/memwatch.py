import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass

from hhlake.kube import cgroup
from hhlake.kube.cgroup import MIB


@dataclass
class Sample:
    t: float
    current: int
    anon: int
    file: int
    kernel: int


@dataclass
class Peaks:
    current: int = 0
    anon: int = 0
    file: int = 0


class Watcher(threading.Thread):
    def __init__(self, interval: float, report_every: float) -> None:
        super().__init__(daemon=True)
        self.interval = interval
        self.report_every = report_every
        self.stop = threading.Event()
        self.t0 = time.monotonic()
        self.peaks = Peaks()

    def sample(self) -> Sample:
        stat = cgroup.memory_stat()
        return Sample(
            round(time.monotonic() - self.t0, 2),
            cgroup.memory_current(),
            stat.get("anon", 0),
            stat.get("file", 0),
            stat.get("kernel", 0),
        )

    def run(self) -> None:
        next_report = 0.0
        while not self.stop.is_set():
            s = self.sample()
            self.peaks.current = max(self.peaks.current, s.current)
            self.peaks.anon = max(self.peaks.anon, s.anon)
            self.peaks.file = max(self.peaks.file, s.file)
            if s.t >= next_report:
                print(
                    f"[mem] {s.t:6.1f} s  current {s.current / MIB:6.0f} MiB  anon {s.anon / MIB:6.0f}  "
                    f"file {s.file / MIB:5.0f}  kernel {s.kernel / MIB:4.0f}",
                    flush=True,
                )
                print("[mem-json] " + json.dumps(asdict(s)), flush=True)
                next_report = s.t + self.report_every
            self.stop.wait(self.interval)


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m hhlake.kube.memwatch")
    p.add_argument("--interval", type=float, default=0.1)
    p.add_argument("--report-every", type=float, default=2.0)
    p.add_argument("command", nargs=argparse.REMAINDER)
    a = p.parse_args()
    command = a.command[1:] if a.command[:1] == ["--"] else a.command
    if not command:
        p.error("command is required")

    print(f"[mem] pod {os.environ.get('HOSTNAME', '?')}: {cgroup.limits().describe()}", flush=True)
    cpu0 = cgroup.cpu_stat()
    watcher = Watcher(a.interval, a.report_every)
    watcher.start()
    t0 = time.monotonic()
    pending: list[int] = []
    children: list[subprocess.Popen[bytes]] = []

    def forward(signum: int, _frame: object) -> None:
        print(f"[mem] got signal {signal.Signals(signum).name} at {time.monotonic() - t0:.1f} s, forwarding to child")
        if children:
            children[0].send_signal(signum)
        else:
            pending.append(signum)

    signal.signal(signal.SIGTERM, forward)
    signal.signal(signal.SIGINT, forward)
    child = subprocess.Popen(command)
    children.append(child)
    for signum in pending:
        child.send_signal(signum)
    code = child.wait()
    if code < 0:
        code = 128 - code
    elapsed = time.monotonic() - t0
    watcher.stop.set()
    watcher.join()

    peak = cgroup.memory_peak()
    events = cgroup.memory_events()
    cpu = cgroup.cpu_stat()
    used = (cpu.get("usage_usec", 0) - cpu0.get("usage_usec", 0)) / 1e6
    throttled = (cpu.get("throttled_usec", 0) - cpu0.get("throttled_usec", 0)) / 1e6
    periods = cpu.get("nr_periods", 0) - cpu0.get("nr_periods", 0)
    nr_throttled = cpu.get("nr_throttled", 0) - cpu0.get("nr_throttled", 0)
    w = watcher.peaks
    print(f"[mem] exit code {code}, wall {elapsed:.1f} s")
    print(
        f"[mem] peak: memory.peak {peak / MIB if peak else float('nan'):.0f} MiB; sampled every {a.interval} s: "
        f"current {w.current / MIB:.0f} MiB, anon {w.anon / MIB:.0f} MiB, file {w.file / MIB:.0f} MiB"
    )
    print("[mem] memory.events: " + ", ".join(f"{k}={v}" for k, v in events.items()))
    print(
        f"[cpu] usage {used:.1f} s over {elapsed:.1f} s wall ({used / elapsed:.2f} CPU avg); "
        f"throttled {throttled:.1f} s in {nr_throttled} of {periods} periods"
    )
    result = {
        "pod": os.environ.get("HOSTNAME"),
        "exit": code,
        "wall": elapsed,
        "memory_max": cgroup.memory_max(),
        "memory_peak": peak,
        "sampled": asdict(w),
        "events": events,
        "cpu_usage": used,
        "cpu_throttled": throttled,
    }
    print("[mem-summary] " + json.dumps(result), flush=True)
    sys.exit(code)


if __name__ == "__main__":
    main()

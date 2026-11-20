from dataclasses import dataclass
from pathlib import Path

ROOT = Path("/sys/fs/cgroup")
MIB = 1 << 20


def _read(name: str) -> str:
    try:
        return (ROOT / name).read_text().strip()
    except OSError:
        return ""


def _flat(name: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for line in _read(name).splitlines():
        key, _, value = line.partition(" ")
        if value.isdigit():
            out[key] = int(value)
    return out


def memory_max() -> int | None:
    raw = _read("memory.max")
    return int(raw) if raw.isdigit() else None


def memory_current() -> int:
    raw = _read("memory.current")
    return int(raw) if raw.isdigit() else 0


def memory_peak() -> int | None:
    raw = _read("memory.peak")
    return int(raw) if raw.isdigit() else None


def memory_stat() -> dict[str, int]:
    return _flat("memory.stat")


def memory_events() -> dict[str, int]:
    return _flat("memory.events")


def cpu_stat() -> dict[str, int]:
    return _flat("cpu.stat")


@dataclass(frozen=True)
class Limits:
    memory_max: int | None
    oom_group: str
    cpu_max: str
    cpu_weight: str

    def describe(self) -> str:
        mem = "max" if self.memory_max is None else f"{self.memory_max / MIB:.0f} MiB"
        quota, _, period = self.cpu_max.partition(" ")
        cpu = "max" if quota == "max" or not period else f"{int(quota) / int(period):g} CPU"
        return f"memory.max {mem}, memory.oom.group {self.oom_group}, cpu.max {cpu}, cpu.weight {self.cpu_weight}"


def limits() -> Limits:
    return Limits(memory_max(), _read("memory.oom.group") or "?", _read("cpu.max") or "?", _read("cpu.weight") or "?")

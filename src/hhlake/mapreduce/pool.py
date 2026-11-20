import contextlib
import multiprocessing as mp
import time
import traceback
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from multiprocessing.connection import Connection, wait
from multiprocessing.process import BaseProcess
from typing import Any

from hhlake.mapreduce.mapper import run_map
from hhlake.mapreduce.reducer import run_reduce
from hhlake.mapreduce.tasks import MapTask, ReduceTask

Task = MapTask | ReduceTask
TASK_ERROR = 1


def task_name(task: Task) -> str:
    if isinstance(task, MapTask):
        return f"m{task.split.index:04d}"
    return f"r{task.partition:03d}"


def run_task(task: Task) -> None:
    if isinstance(task, MapTask):
        run_map(task)
    else:
        run_reduce(task)


def worker_loop(conn: Connection) -> None:
    while (task := conn.recv()) is not None:
        try:
            run_task(task)
            conn.send(0)
        except Exception:
            traceback.print_exc()
            conn.send(TASK_ERROR)


@dataclass(frozen=True)
class Watchdog:
    timeout: float | None = None
    kill_after: dict[str, float] = field(default_factory=dict)
    tick: float = 0.2

    def wait_timeout(self) -> float | None:
        return self.tick if self.timeout or self.kill_after else None

    def verdict(self, task: Task, elapsed: float) -> str | None:
        delay = self.kill_after.get(task_name(task))
        if task.attempt == 1 and delay is not None and elapsed >= delay:
            return "external kill"
        if self.timeout is not None and elapsed >= self.timeout:
            return "task timeout"
        return None

    def enforce(self, proc: BaseProcess, task: Task, elapsed: float) -> None:
        reason = self.verdict(task, elapsed)
        if reason and proc.is_alive():
            print(
                f"[master] {reason}: killing pid {proc.pid} ({task_name(task)} attempt {task.attempt}) "
                f"after {elapsed:.1f} s"
            )
            proc.kill()


@dataclass
class Worker:
    proc: BaseProcess
    conn: Any
    task: Task | None = None
    started: float = 0.0


@dataclass
class Finished:
    task: Task
    exitcode: int | None
    seconds: float


class WorkerPool:
    def __init__(self, size: int, watchdog: Watchdog) -> None:
        self.ctx = mp.get_context("spawn")
        self.size = size
        self.watchdog = watchdog
        self.workers: list[Worker] = []
        self.spawned = 0

    def _spawn(self) -> Worker:
        parent, child = self.ctx.Pipe()
        proc = self.ctx.Process(target=worker_loop, args=(child,), name=f"worker-{self.spawned}")
        proc.start()
        child.close()
        self.spawned += 1
        return Worker(proc, parent)

    def start(self) -> None:
        while len(self.workers) < self.size:
            self.workers.append(self._spawn())

    def idle(self) -> list[Worker]:
        for i, w in enumerate(self.workers):
            if w.task is None and not w.proc.is_alive():
                w.proc.join()
                w.conn.close()
                self.workers[i] = self._spawn()
        return [w for w in self.workers if w.task is None]

    def busy(self) -> list[Worker]:
        return [w for w in self.workers if w.task is not None]

    def submit(self, worker: Worker, task: Task) -> None:
        worker.task, worker.started = task, time.perf_counter()
        worker.conn.send(task)

    def collect(self) -> list[Finished]:
        busy = self.busy()
        handles = [w.conn for w in busy] + [w.proc.sentinel for w in busy]
        ready = set(wait(handles, timeout=self.watchdog.wait_timeout()))
        done: list[Finished] = []
        for i, w in enumerate(self.workers):
            if w.task is None:
                continue
            elapsed = time.perf_counter() - w.started
            if w.conn not in ready and w.proc.sentinel not in ready:
                self.watchdog.enforce(w.proc, w.task, elapsed)
                continue
            task = w.task
            if w.conn in ready:
                try:
                    code: int | None = w.conn.recv()
                    w.task = None
                    done.append(Finished(task, code, elapsed))
                    continue
                except (EOFError, ConnectionResetError, OSError):
                    pass
            if w.proc.is_alive():
                w.proc.kill()
            w.proc.join()
            w.conn.close()
            self.workers[i] = self._spawn()
            done.append(Finished(task, w.proc.exitcode, elapsed))
        return done

    def close(self) -> None:
        for w in self.workers:
            with contextlib.suppress(BrokenPipeError, OSError):
                w.conn.send(None)
        for w in self.workers:
            w.proc.join(timeout=10)
            if w.proc.is_alive():
                w.proc.kill()
                w.proc.join()
        self.workers = []


class ProcessPerTask:
    def __init__(self, size: int, watchdog: Watchdog) -> None:
        self.ctx = mp.get_context("spawn")
        self.size = size
        self.watchdog = watchdog
        self.running: dict[int, tuple[BaseProcess, Task, float]] = {}
        self.spawned = 0

    def start(self) -> None:
        pass

    def has_slot(self) -> bool:
        return len(self.running) < self.size

    def submit_new(self, task: Task) -> None:
        proc = self.ctx.Process(target=run_task, args=(task,), name=task_name(task))
        proc.start()
        self.spawned += 1
        self.running[proc.sentinel] = (proc, task, time.perf_counter())

    def any_busy(self) -> bool:
        return bool(self.running)

    def collect(self) -> list[Finished]:
        ready = set(wait(list(self.running), timeout=self.watchdog.wait_timeout()))
        done = []
        for sentinel in list(self.running):
            proc, task, started = self.running[sentinel]
            elapsed = time.perf_counter() - started
            if sentinel not in ready:
                self.watchdog.enforce(proc, task, elapsed)
                continue
            del self.running[sentinel]
            proc.join()
            done.append(Finished(task, proc.exitcode, elapsed))
        return done

    def close(self) -> None:
        for proc, _, _ in self.running.values():
            proc.kill()
            proc.join()
        self.running = {}


def drive(
    pool: WorkerPool | ProcessPerTask,
    tasks: list[Task],
    on_finished: Callable[[Finished], Task | None],
) -> None:
    queue: deque[Task] = deque(tasks)
    while True:
        if isinstance(pool, WorkerPool):
            for w in pool.idle():
                if not queue:
                    break
                pool.submit(w, queue.popleft())
            busy = bool(pool.busy())
        else:
            while queue and pool.has_slot():
                pool.submit_new(queue.popleft())
            busy = pool.any_busy()
        if not busy:
            return
        for fin in pool.collect():
            again = on_finished(fin)
            if again is not None:
                queue.append(again)

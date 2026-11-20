import json
from pathlib import Path

from hhlake.kube.commit import merge_map_stats, merge_summaries
from hhlake.kube.shuffle import Run
from hhlake.kube.sizing import MIB, recommend, summaries


def test_recommend_rounds_up_to_step() -> None:
    assert recommend(539 * MIB, 1.2, 64) == 704
    assert recommend(80 * MIB, 1.2, 64) == 128
    assert recommend(640 * MIB, 1.0, 64) == 640


def test_summaries_reads_only_tagged_lines(tmp_path: Path) -> None:
    line = {"pod": "p", "exit": 0, "memory_peak": 5 * MIB, "sampled": {"anon": MIB}}
    (tmp_path / "p.log").write_text(f"[mem] noise\n[mem-summary] {json.dumps(line)}\n", encoding="utf-8")
    assert summaries([tmp_path]) == [line]


def test_run_prefixes() -> None:
    run = Run("par", 32, 4, Path("/work"))
    assert run.map_prefix(7) == "shuffle/par/m0007"
    assert run.reduce_prefix(2) == "shuffle/par/r002"
    assert run.output == "results/k8s/par"


def test_merge_map_stats_sums_counters_and_stacks() -> None:
    base = {"bytes_fetched": 10, "cpu_seconds": 1.0, "lines": 3, "parsed": 2, "in_variant": 1, "with_skills": 1}
    a = base | {"emitted": {"1": 4, "2": 6}, "written": {"1": 4, "2": 5}}
    b = base | {"emitted": {"1": 1, "2": 0}, "written": {"1": 1, "2": 0}}
    totals = merge_map_stats([a, b])
    assert totals["lines"] == 6
    assert totals["emitted"] == {1: 5, 2: 6}
    assert totals["written"] == {1: 5, 2: 5}


def test_merge_summaries_keeps_global_top() -> None:
    r0 = {"2": {"distinct": 2, "total": 9, "top": [[["c++", "linux"], 8], [["a", "b"], 1]]}}
    r1 = {"2": {"distinct": 1, "total": 3, "top": [[["git", "linux"], 3]]}}
    merged = merge_summaries([r0, r1])
    assert merged[2]["distinct"] == 3
    assert merged[2]["total"] == 12
    assert [n for _, n in merged[2]["top"]] == [8, 3, 1]

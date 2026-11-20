import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import duckdb
from botocore.exceptions import ClientError

from hhlake.duck import connect
from hhlake.s3 import make_client
from hhlake.settings import BUCKET, STACK_NAMES


@dataclass(frozen=True)
class Result:
    prefix: str
    kind: str
    in_variant: int
    with_skills: int

    def uri(self, name: str) -> str:
        if self.kind == "MapReduce":
            return f"s3://{BUCKET}/{self.prefix}/{name}/part-r-*.csv"
        return f"s3://{BUCKET}/{self.prefix}/{name}.csv"


def locate(prefix: str) -> Result:
    s3 = make_client()
    try:
        meta = json.loads(s3.get_object(Bucket=BUCKET, Key=f"{prefix}/_job.json")["Body"].read())["map"]
    except ClientError:
        meta = None
    if meta is not None:
        try:
            s3.head_object(Bucket=BUCKET, Key=f"{prefix}/_SUCCESS")
        except ClientError as e:
            raise SystemExit(f"s3://{BUCKET}/{prefix}/ has no _SUCCESS marker: the job did not finish") from e
        return Result(prefix, "MapReduce", meta["in_variant"], meta["with_skills"])
    else:
        meta = json.loads(s3.get_object(Bucket=BUCKET, Key=f"{prefix}/_summary.json")["Body"].read())
        return Result(prefix, "DuckDB", meta["in_variant"], meta["with_skills"])


def _reader(uri: str, k: int) -> str:
    cols = {f"skill{i}": "VARCHAR" for i in range(1, k + 1)} | {"vacancies": "BIGINT"}
    spec = ", ".join(f"'{c}': '{t}'" for c, t in cols.items())
    return f"read_csv('{uri}', header = true, columns = {{{spec}}})"


def compare(con: duckdb.DuckDBPyConnection, a: Result, b: Result, k: int) -> dict:
    name = STACK_NAMES[k]
    keys = [f"skill{i}" for i in range(1, k + 1)]
    on = " AND ".join(f"x.{c} = y.{c}" for c in keys)
    row = con.sql(
        f"""
        WITH x AS (SELECT * FROM {_reader(a.uri(name), k)}), y AS (SELECT * FROM {_reader(b.uri(name), k)})
        SELECT
            (SELECT count(*) FROM x), (SELECT sum(vacancies) FROM x),
            (SELECT count(*) FROM y), (SELECT sum(vacancies) FROM y),
            count(*) FILTER (WHERE y.vacancies IS NULL),
            count(*) FILTER (WHERE x.vacancies IS NULL),
            count(*) FILTER (WHERE x.vacancies <> y.vacancies),
            (SELECT count(*) - count(DISTINCT ({", ".join(keys)})) FROM x)
              + (SELECT count(*) - count(DISTINCT ({", ".join(keys)})) FROM y)
        FROM x FULL OUTER JOIN y ON {on}
        """
    ).fetchall()[0]
    fields = ["a_rows", "a_sum", "b_rows", "b_sum", "only_a", "only_b", "count_diff", "dup_keys"]
    return {"stack": name, **dict(zip(fields, row, strict=True))}


def top(con: duckdb.DuckDBPyConnection, r: Result, k: int, n: int) -> list[tuple]:
    keys = ", ".join(f"skill{i}" for i in range(1, k + 1))
    rel = _reader(r.uri(STACK_NAMES[k]), k)
    return con.sql(f"SELECT {keys}, vacancies FROM {rel} ORDER BY vacancies DESC, {keys} LIMIT {n}").fetchall()


def print_top(con: duckdb.DuckDBPyConnection, a: Result, b: Result, n: int) -> bool:
    ta, tb = top(con, a, 2, n), top(con, b, 2, n)
    print(f"top-{n} pairs: A | B")
    for i, (x, y) in enumerate(zip(ta, tb, strict=True), 1):
        left, right = f"{x[0]} + {x[1]}  {x[2]}", f"{y[0]} + {y[1]}  {y[2]}"
        print(f"{i:>3}  {left:<28}| {right:<28}{'=' if x == y else 'DIFFERENT'}")
    return ta == tb


def export(con: duckdb.DuckDBPyConnection, a: Result, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for k, name in STACK_NAMES.items():
        keys = ", ".join(f"skill{i}" for i in range(1, k + 1))
        path = (out / f"{name}.csv").as_posix()
        con.execute(
            f"COPY (SELECT * FROM {_reader(a.uri(name), k)} ORDER BY vacancies DESC, {keys}) TO '{path}' (HEADER)"
        )
    print(f"exported {a.kind} result to {out}/{{{','.join(STACK_NAMES.values())}}}.csv")


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m hhlake.verify")
    p.add_argument("--a", default="results/mapreduce")
    p.add_argument("--b", default="results/duckdb")
    p.add_argument("--export", type=Path, help="save A as one sorted csv per stack size")
    p.add_argument("--top", type=int, default=0, help="print top-N pairs of A and B side by side")
    args = p.parse_args()

    con = connect()
    a, b = locate(args.a), locate(args.b)
    print(f"A = {a.kind:<9} s3://{BUCKET}/{a.prefix}/")
    print(f"B = {b.kind:<9} s3://{BUCKET}/{b.prefix}/")
    ok = a.in_variant == b.in_variant and a.with_skills == b.with_skills
    print(
        f"variant vacancies: A {a.in_variant:,} / B {b.in_variant:,}; "
        f"with key_skills: A {a.with_skills:,} / B {b.with_skills:,}  {'MATCH' if ok else 'MISMATCH'}"
    )
    print(f"{'stack':<8}{'A rows':>9}{'A sum':>10}{'B rows':>9}{'B sum':>10}{'only A':>8}{'only B':>8}{'diff':>6}")
    for k in STACK_NAMES:
        r = compare(con, a, b, k)
        same = r["only_a"] == r["only_b"] == r["count_diff"] == r["dup_keys"] == 0
        same = same and r["a_rows"] == r["b_rows"] and r["a_sum"] == r["b_sum"]
        ok &= same
        print(
            f"{r['stack']:<8}{r['a_rows']:>9,}{r['a_sum']:>10,}{r['b_rows']:>9,}{r['b_sum']:>10,}"
            f"{r['only_a']:>8}{r['only_b']:>8}{r['count_diff']:>6}  {'MATCH' if same else 'MISMATCH'}"
        )
    if args.top:
        same_top = print_top(con, a, b, args.top)
        print(f"top-{args.top} pairs {'identical' if same_top else 'DIFFERENT'}")
        ok &= same_top
    print("RESULT:", "all three stacks are identical" if ok else "MISMATCH")
    if args.export:
        export(con, a, args.export)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

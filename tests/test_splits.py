import random

import pytest

from hhlake.mapreduce import splits
from hhlake.mapreduce.splits import Split, iter_split_lines, plan_splits


def chunked(data: bytes, begin: int, step: int):
    for i in range(begin, len(data), step):
        yield data[i : i + step]


def read_all(data: bytes, chunk: int, block: int) -> list[bytes]:
    lines: list[bytes] = []
    for split in plan_splits(len(data), chunk):
        begin = max(split.start - 1, 0)
        lines.extend(iter_split_lines(chunked(data, begin, block), split))
    return lines


def make_file(rows: int, seed: int) -> bytes:
    rnd = random.Random(seed)
    header = b"id,name,key_skills"
    body = [f"{i},{'x' * rnd.randint(0, 40)},C++; Linux".encode() for i in range(rows)]
    return b"\n".join([header, *body]) + b"\n"


def test_plan_covers_file_without_gaps() -> None:
    splits = plan_splits(1000, 300)
    assert splits[0] == Split(0, 0, 300)
    assert splits[-1].end == 1000
    assert all(a.end == b.start for a, b in zip(splits, splits[1:], strict=False))


@pytest.mark.parametrize("chunk", [1, 7, 33, 64, 100, 4096])
@pytest.mark.parametrize("block", [1, 5, 1024])
def test_every_line_read_exactly_once(chunk: int, block: int) -> None:
    data = make_file(200, seed=chunk * block)
    expected = data.rstrip(b"\n").split(b"\n")[1:]
    assert read_all(data, chunk, block) == expected


def test_split_boundary_on_newline() -> None:
    data = b"h\naaa\nbbb\nccc\n"
    boundary = data.index(b"bbb")
    assert read_all(data, boundary, 3) == [b"aaa", b"bbb", b"ccc"]


def test_file_without_trailing_newline() -> None:
    data = b"h\na\nb\nlast"
    assert read_all(data, 3, 2) == [b"a", b"b", b"last"]


class FakeBody:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def iter_chunks(self, size: int):
        for i in range(0, len(self.data), size):
            yield self.data[i : i + size]

    def close(self) -> None:
        pass


class FakeS3:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.ranges: list[tuple[int, int]] = []

    def get_object(self, Bucket: str, Key: str, Range: str) -> dict:
        first, last = (int(x) for x in Range.removeprefix("bytes=").split("-"))
        self.ranges.append((first, last))
        return {"Body": FakeBody(self.data[first : last + 1])}


def test_line_longer_than_overflow_is_read_with_extra_ranges(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(splits, "OVERFLOW", 8)
    monkeypatch.setattr(splits, "READ_BLOCK", 4)
    long_line = b"y" * 50
    data = b"h\n" + b"a,1\n" + long_line + b"\nb,2\n"
    s3 = FakeS3(data)
    lines: list[bytes] = []
    for split in plan_splits(len(data), 10):
        lines.extend(iter_split_lines(splits.split_chunks(s3, "b", "k", split, len(data)), split))
    assert lines == [b"a,1", long_line, b"b,2"]
    assert len(s3.ranges) > len(plan_splits(len(data), 10))

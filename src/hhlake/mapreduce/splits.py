from collections.abc import Iterator
from dataclasses import dataclass

from botocore.client import BaseClient

READ_BLOCK = 1 << 20
OVERFLOW = 64 << 10


@dataclass(frozen=True)
class Split:
    index: int
    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start


def plan_splits(size: int, chunk_bytes: int) -> list[Split]:
    bounds = list(range(0, size, chunk_bytes)) + [size]
    return [Split(i, a, b) for i, (a, b) in enumerate(zip(bounds, bounds[1:], strict=False))]


def _ranged_chunks(client: BaseClient, bucket: str, key: str, begin: int, first_end: int, size: int) -> Iterator[bytes]:
    frm, to = begin, first_end
    while frm < size:
        body = client.get_object(Bucket=bucket, Key=key, Range=f"bytes={frm}-{to - 1}")["Body"]
        try:
            yield from body.iter_chunks(READ_BLOCK)
        finally:
            body.close()
        frm, to = to, min(to + OVERFLOW, size)


def iter_split_lines(chunks: Iterator[bytes], split: Split) -> Iterator[bytes]:
    line_start = max(split.start - 1, 0)
    drop_first = True
    pending = b""
    for chunk in chunks:
        data = pending + chunk
        cut = 0
        while (nl := data.find(b"\n", cut)) != -1:
            if line_start >= split.end:
                return
            if drop_first:
                drop_first = False
            else:
                yield data[cut:nl]
            line_start += nl - cut + 1
            cut = nl + 1
        pending = data[cut:]
    if pending and line_start < split.end and not drop_first:
        yield pending


def split_chunks(client: BaseClient, bucket: str, key: str, split: Split, size: int) -> Iterator[bytes]:
    begin = max(split.start - 1, 0)
    first_end = min(split.end + OVERFLOW, size)
    return _ranged_chunks(client, bucket, key, begin, first_end, size)

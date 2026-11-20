import io

from botocore.client import BaseClient


class S3RangeFile(io.RawIOBase):
    def __init__(self, client: BaseClient, bucket: str, key: str, size: int | None = None) -> None:
        self.client = client
        self.bucket = bucket
        self.key = key
        self.size = size if size is not None else client.head_object(Bucket=bucket, Key=key)["ContentLength"]
        self.pos = 0
        self.fetched = 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        base = {io.SEEK_SET: 0, io.SEEK_CUR: self.pos, io.SEEK_END: self.size}[whence]
        self.pos = max(0, min(base + offset, self.size))
        return self.pos

    def readinto(self, buffer: memoryview) -> int:  # type: ignore[override]
        n = min(len(buffer), self.size - self.pos)
        if n <= 0:
            return 0
        rng = f"bytes={self.pos}-{self.pos + n - 1}"
        data = self.client.get_object(Bucket=self.bucket, Key=self.key, Range=rng)["Body"].read()
        buffer[: len(data)] = data
        self.pos += len(data)
        self.fetched += len(data)
        return len(data)

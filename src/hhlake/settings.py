import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class S3Settings:
    endpoint: str = field(default_factory=lambda: os.environ.get("S3_ENDPOINT", "http://localhost:9000"))
    access_key: str = field(default_factory=lambda: os.environ.get("AWS_ACCESS_KEY_ID", "labadmin"))
    secret_key: str = field(default_factory=lambda: os.environ.get("AWS_SECRET_ACCESS_KEY", "labsecret123"))
    region: str = "us-east-1"

    @property
    def host(self) -> str:
        return self.endpoint.split("://", 1)[-1]


BUCKET = "hh-lake"
RAW_KEY = "raw/it_vacancies_2024.csv"
RAW_URI = f"s3://{BUCKET}/{RAW_KEY}"
STACK_NAMES = {1: "skills", 2: "pairs", 3: "triples"}

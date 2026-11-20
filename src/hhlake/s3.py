import boto3
from botocore.client import BaseClient
from botocore.config import Config

from hhlake.settings import S3Settings


def make_client(settings: S3Settings | None = None) -> BaseClient:
    s = settings or S3Settings()
    return boto3.client(
        "s3",
        endpoint_url=s.endpoint,
        aws_access_key_id=s.access_key,
        aws_secret_access_key=s.secret_key,
        region_name=s.region,
        config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 5, "mode": "standard"}),
    )

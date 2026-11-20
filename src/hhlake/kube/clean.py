import argparse
import time

from hhlake.kube.shuffle import list_keys
from hhlake.s3 import make_client
from hhlake.settings import BUCKET


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m hhlake.kube.clean")
    target = p.add_mutually_exclusive_group(required=True)
    target.add_argument("--run", help="remove shuffle/<run>/ and results/k8s/<run>/")
    target.add_argument("--prefix", help="remove everything under this prefix")
    a = p.parse_args()
    prefixes = [f"shuffle/{a.run}/", f"results/k8s/{a.run}/"] if a.run else [a.prefix.rstrip("/") + "/"]
    s3 = make_client()
    t0 = time.perf_counter()
    removed = 0
    for prefix in prefixes:
        keys = list_keys(s3, BUCKET, prefix)
        for i in range(0, len(keys), 1000):
            batch = [{"Key": k} for k in keys[i : i + 1000]]
            s3.delete_objects(Bucket=BUCKET, Delete={"Objects": batch, "Quiet": True})
        removed += len(keys)
    print(f"{', '.join(prefixes)}: removed {removed} old objects in {time.perf_counter() - t0:.1f} s")


if __name__ == "__main__":
    main()

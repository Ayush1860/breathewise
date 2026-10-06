"""Smoke load test for the read endpoints: N concurrent users, report latency and errors.

uv run python infra/scripts/load_test.py https://<cloudfront-domain> --users 100 --requests 1000
"""

import argparse
import statistics
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from itertools import cycle, islice

PATHS = ("/aqi/current", "/aqi/forecast", "/stations", "/scoreboard", "/metrics", "/health")


def hit(url: str) -> tuple[float, int]:
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    except (urllib.error.URLError, TimeoutError, OSError):
        status = 0
    return time.perf_counter() - start, status


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url")
    parser.add_argument("--users", type=int, default=100)
    parser.add_argument("--requests", type=int, default=1000)
    args = parser.parse_args()
    urls = [args.base_url.rstrip("/") + p for p in islice(cycle(PATHS), args.requests)]
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.users) as pool:
        results = list(pool.map(hit, urls))
    elapsed = time.perf_counter() - started
    latencies = sorted(r[0] * 1000 for r in results)
    errors = [s for _, s in results if s != 200]
    p95 = latencies[int(0.95 * (len(latencies) - 1))]
    print(f"{len(results)} requests, {args.users} concurrent users, {elapsed:.1f} s")
    print(
        f"p50 {statistics.median(latencies):.0f} ms | p95 {p95:.0f} ms | max {latencies[-1]:.0f} ms"
    )
    print(f"errors: {len(errors)} {sorted(set(errors)) if errors else ''}")
    if errors or p95 > 1000:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

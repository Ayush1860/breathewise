"""Small JSON-over-HTTP helper with timeouts and retries (stdlib only, Lambda-friendly)."""

import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

Opener = Callable[[urllib.request.Request, float], bytes]


class SourceError(Exception):
    """An upstream source failed or returned unusable data."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _urlopen(request: urllib.request.Request, timeout: float) -> bytes:
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return response.read()


def _retryable(status: int | None) -> bool:
    return status is None or status == 429 or status >= 500


def get_json(
    url: str,
    params: Mapping[str, str | int | float] | None = None,
    headers: Mapping[str, str] | None = None,
    *,
    timeout: float = 10.0,
    attempts: int = 3,
    backoff_s: float = 1.0,
    opener: Opener = _urlopen,
    sleep: Callable[[float], None] = time.sleep,
) -> Any:
    full_url = f"{url}?{urllib.parse.urlencode(params)}" if params else url
    request = urllib.request.Request(full_url, headers=dict(headers or {}))
    last_error: SourceError | None = None
    for attempt in range(attempts):
        try:
            body = opener(request, timeout)
        except urllib.error.HTTPError as exc:
            last_error = SourceError(f"HTTP {exc.code} from {url}", status=exc.code)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = SourceError(f"{type(exc).__name__} from {url}: {exc}")
        else:
            try:
                return json.loads(body)
            except ValueError as exc:
                raise SourceError(f"invalid JSON from {url}") from exc
        if not _retryable(last_error.status) or attempt == attempts - 1:
            break
        sleep(backoff_s * 2**attempt + random.uniform(0, backoff_s))
    assert last_error is not None
    raise last_error

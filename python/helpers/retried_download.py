import time
from typing import Callable

import requests

from python.log.console import Console


def retried_download(
    name: str,
    do_request: Callable[[], requests.Response],
    *,
    max_tries: int = -1,
    timeout_max_secs: float = 5,
    timeout_min_secs: float = 0.3,
    timeout_step_secs: float = 0.2,
    response_ok: Callable[[requests.Response], bool] = lambda x: x.ok,
) -> requests.Response | None:
    response: requests.Response | None = None
    page_try = 0
    while not response:
        page_try += 1
        Console.log_dim(f"Fetching {name}...", return_line=True)
        response = do_request()

        if max_tries > 0 and page_try > max_tries:
            Console.log_dim(f"Giving up on {name} after {page_try} tries")
            return None

        if response.status_code == 403:
            Console.log_dim(
                f"Got 403 fetching {name}. Retrying... (Attempt {page_try})",
                return_line=True,
            )
            time.sleep(
                min(
                    timeout_min_secs + timeout_step_secs * page_try,
                    timeout_max_secs,
                )
            )
            response = None
            continue

        if not response_ok(response):
            Console.log_dim(f"Couldn't fetch {name}")
            return None

    return response

import copy
import os
from typing import Self, cast
import urllib.parse
import requests


class PlayerDeobfuscator:
    _endpoint: str
    _http: requests.Session

    def __init__(
        self, *, endpoint: str | None = None, http: requests.Session | None = None
    ) -> None:
        self._endpoint = endpoint or os.getenv(
            "DOWNLOADERS_PLAYER_DEOBFUSCATOR_ENDPOINT",
            "https://player-deobfuscator.fxk.ch",
        )

        self._http = http or requests.Session()

    def set_endpoint(self, endpoint: str) -> Self:
        self._endpoint = endpoint
        return self

    def with_endopint(self, endpoint: str) -> Self:
        return copy.deepcopy(self).set_endpoint(endpoint)

    def set_http(self, http: requests.Session) -> Self:
        self._http = http
        return self

    def with_http(self, http: requests.Session) -> Self:
        return copy.deepcopy(self).set_http(http)

    def get(self, url: str, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs):
        return self.request("POST", url, **kwargs)

    def request(self, method: str, url: str, *, validate_status: bool = True, **kwargs):
        url = urllib.parse.urljoin(self._endpoint, url)

        resp = requests.request(method, url, **kwargs)

        if validate_status:
            try:
                resp.raise_for_status()
            except Exception:
                return None

        try:
            return cast(dict, resp.json())
        except Exception:
            return None


DefaultPlayerDeobfuscator = PlayerDeobfuscator()

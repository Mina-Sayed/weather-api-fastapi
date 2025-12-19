from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class WeatherstackError(Exception):
    code: int | None
    type: str | None
    info: str


class WeatherstackClient:
    def __init__(
        self,
        *,
        http: httpx.AsyncClient,
        api_key: str,
        base_url: str,
    ) -> None:
        self._http = http
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")

    async def get_current(self, *, city: str) -> dict[str, Any]:
        url = f"{self._base_url}/current"
        params = {"access_key": self._api_key, "query": city}

        resp = await self._http.get(url, params=params)
        resp.raise_for_status()

        data = resp.json()

        if data.get("success") is False and "error" in data:
            err = data.get("error") or {}
            raise WeatherstackError(
                code=err.get("code"),
                type=err.get("type"),
                info=str(err.get("info") or ""),
            )

        if "location" not in data or "current" not in data:
            raise WeatherstackError(code=None, type=None, info="Unexpected response from Weatherstack")

        return data

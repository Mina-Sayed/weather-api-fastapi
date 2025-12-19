from __future__ import annotations

import logging
import threading
import time
from contextlib import asynccontextmanager
from typing import Any, Optional

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel

from app.schemas import WeatherResponse
from app.settings import Settings
from app.weatherstack_client import WeatherstackClient, WeatherstackError


logger = logging.getLogger("weather_api")
logging.basicConfig(level=logging.INFO)

settings = Settings()


class _TTLCache:
    def __init__(self, *, ttl_seconds: int) -> None:
        self._ttl_seconds = ttl_seconds
        self._data: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        now = time.time()
        with self._lock:
            item = self._data.get(key)
            if not item:
                return None

            expires_at, value = item
            if expires_at <= now:
                self._data.pop(key, None)
                return None

            return value

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = (time.time() + self._ttl_seconds, value)


def get_settings() -> Settings:
    return Settings()


def get_cache(settings: Settings = Depends(get_settings)) -> _TTLCache:
    return _TTLCache(ttl_seconds=settings.cache_ttl_seconds)


def get_http_client(settings: Settings = Depends(get_settings)) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=httpx.Timeout(settings.http_timeout_seconds))


def get_weatherstack_client(
    http: httpx.AsyncClient = Depends(get_http_client),
    settings: Settings = Depends(get_settings),
) -> WeatherstackClient:
    return WeatherstackClient(
        http=http,
        api_key=settings.weatherstack_api_key,
        base_url=settings.weatherstack_base_url,
    )


def _require_int(value: Any, *, field: str) -> int:
    if value is None:
        raise ValueError(f"Missing field: {field}")
    try:
        return int(value)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Invalid integer field: {field}") from e


def _map_weatherstack_payload(data: dict[str, Any]) -> WeatherResponse:
    location = data.get("location") or {}
    current = data.get("current") or {}

    return WeatherResponse(
        city=str(location.get("name") or ""),
        country=location.get("country"),
        localtime=location.get("localtime"),
        temperature_c=_require_int(current.get("temperature"), field="current.temperature"),
        weather_descriptions=list(current.get("weather_descriptions") or []),
        wind_speed=current.get("wind_speed"),
        wind_dir=current.get("wind_dir"),
        humidity=current.get("humidity"),
        feelslike_c=current.get("feelslike"),
        uv_index=current.get("uv_index"),
        visibility_km=current.get("visibility"),
    )


def _http_exception_from_weatherstack_error(err: WeatherstackError) -> HTTPException:
    # Based on Weatherstack documentation error codes/types.
    if err.code == 101 or err.type == "unauthorized":
        return HTTPException(status_code=401, detail="Weatherstack unauthorized")

    if err.code == 104 or err.type == "usage_limit_reached":
        return HTTPException(status_code=429, detail="Weatherstack usage limit reached")

    if err.code == 429 or err.type == "too_many_requests":
        return HTTPException(status_code=429, detail="Weatherstack too many requests")

    if err.code == 403 or err.type == "forbidden":
        return HTTPException(status_code=403, detail="Weatherstack forbidden")

    if err.code == 601 or err.type == "missing_query":
        return HTTPException(status_code=400, detail="Missing city query")

    return HTTPException(status_code=502, detail=f"Weatherstack error: {err.info}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="Weather API", version="1.0.0", lifespan=lifespan)


@app.get("/weather", response_model=WeatherResponse)
async def get_weather(
    city: str = Query(min_length=1, max_length=100),
    client: WeatherstackClient = Depends(get_weatherstack_client),
    cache: _TTLCache = Depends(get_cache),
    settings: Settings = Depends(get_settings),
) -> WeatherResponse:
    normalized = city.strip()
    if not normalized:
        raise HTTPException(status_code=422, detail="city must not be empty")

    cache_key = normalized.casefold()

    if settings.cache_enabled:
        cached = cache.get(cache_key)
        if cached is not None:
            logger.info("cache hit city=%s", normalized)
            return cached

    start = time.perf_counter()
    try:
        payload = await client.get_current(city=normalized)
    except WeatherstackError as e:
        raise _http_exception_from_weatherstack_error(e) from e
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Weatherstack request timed out")
    except httpx.HTTPStatusError:
        raise HTTPException(status_code=502, detail="Weatherstack request failed")
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="Weatherstack network error")
    finally:
        logger.info("weatherstack request city=%s duration_ms=%.2f", normalized, (time.perf_counter() - start) * 1000)

    try:
        response = _map_weatherstack_payload(payload)
    except ValueError as e:
        raise HTTPException(status_code=502, detail="Unexpected response from Weatherstack") from e

    if settings.cache_enabled:
        cache.set(cache_key, response)

    return response

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request

from app.schemas import WeatherResponse
from app.settings import Settings
from app.weatherstack_client import WeatherstackClient, WeatherstackError


logger = logging.getLogger("weather_api")

_MAX_CACHE_SIZE = 1000


class _TTLCache:
    """
    Async-safe TTL cache with bounded size and deterministic eviction.
    Eviction policy: FIFO based on insertion time.
    """

    def __init__(self, *, ttl_seconds: int, max_size: int = _MAX_CACHE_SIZE) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_size = max_size
        self._data: dict[str, tuple[float, float, Any]] = {}
        self._counter = 0.0
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Any | None:
        now = time.time()
        async with self._lock:
            item = self._data.get(key)
            if not item:
                return None

            expires_at, _, value = item
            if expires_at <= now:
                self._data.pop(key, None)
                return None

            return value

    async def set(self, key: str, value: Any) -> None:
        async with self._lock:
            now = time.time()

            # Remove expired entries
            self._data = {
                k: v for k, v in self._data.items() if v[0] > now
            }

            # Enforce max size (FIFO eviction)
            if len(self._data) >= self._max_size:
                oldest_key = min(self._data, key=lambda k: self._data[k][1])
                self._data.pop(oldest_key, None)

            self._counter += 1
            self._data[key] = (now + self._ttl_seconds, self._counter, value)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def get_cache(request: Request) -> _TTLCache:
    return request.app.state.cache


def get_weatherstack_client(request: Request) -> WeatherstackClient:
    return request.app.state.weatherstack_client


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _map_weatherstack_payload(data: dict[str, Any]) -> WeatherResponse:
    location = data.get("location") or {}
    current = data.get("current") or {}

    temperature = _safe_int(current.get("temperature"))
    if temperature is None:
        raise ValueError("Invalid temperature")

    return WeatherResponse(
        city=str(location.get("name") or ""),
        country=location.get("country"),
        localtime=location.get("localtime"),
        temperature_c=temperature,
        weather_descriptions=list(current.get("weather_descriptions") or []),
        wind_speed=_safe_int(current.get("wind_speed")),
        wind_dir=current.get("wind_dir"),
        humidity=_safe_int(current.get("humidity")),
        feelslike_c=_safe_int(current.get("feelslike")),
        uv_index=_safe_int(current.get("uv_index")),
        visibility_km=_safe_int(current.get("visibility")),
    )


def _http_exception_from_weatherstack_error(err: WeatherstackError) -> HTTPException:
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

    return HTTPException(status_code=502, detail="Upstream Weatherstack error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.http_timeout_seconds)
    )

    app.state.weatherstack_client = WeatherstackClient(
        http=http_client,
        api_key=settings.weatherstack_api_key,
        base_url=settings.weatherstack_base_url,
    )

    app.state.cache = _TTLCache(
        ttl_seconds=settings.cache_ttl_seconds,
        max_size=_MAX_CACHE_SIZE,
    )

    logger.info("Application started")
    try:
        yield
    finally:
        await http_client.aclose()
        logger.info("Application shutdown")


app = FastAPI(
    title="Weather API",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


@app.get("/weather", response_model=WeatherResponse)
async def get_weather(
    city: str = Query(min_length=1, max_length=100),
    client: WeatherstackClient = Depends(get_weatherstack_client),
    cache: _TTLCache = Depends(get_cache),
    settings: Settings = Depends(get_settings),
) -> WeatherResponse:
    normalized = " ".join(city.split())
    if not normalized:
        raise HTTPException(status_code=422, detail="city must not be empty")

    cache_key = normalized.casefold()

    if settings.cache_enabled:
        cached = await cache.get(cache_key)
        if cached is not None:
            logger.info("cache hit city=%s", normalized)
            return cached

    start = time.perf_counter()
    try:
        payload = await client.get_current(city=normalized)
    except WeatherstackError as e:
        logger.warning(
            "weatherstack error code=%s type=%s info=%s",
            e.code,
            e.type,
            e.info,
        )
        raise _http_exception_from_weatherstack_error(e) from e
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Weatherstack timeout")
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="Weatherstack network error")
    finally:
        logger.info(
            "weatherstack request city=%s duration_ms=%.2f",
            normalized,
            (time.perf_counter() - start) * 1000,
        )

    try:
        response = _map_weatherstack_payload(payload)
    except ValueError:
        raise HTTPException(
            status_code=502,
            detail="Unexpected response from Weatherstack",
        )

    if settings.cache_enabled:
        # store a copy to avoid mutation bugs
        await cache.set(cache_key, response.model_copy())

    return response

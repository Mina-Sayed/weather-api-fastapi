from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class WeatherResponse(BaseModel):
    city: str
    country: Optional[str] = None
    localtime: Optional[str] = None

    temperature_c: int
    weather_descriptions: list[str]

    wind_speed: Optional[int] = None
    wind_dir: Optional[str] = None
    humidity: Optional[int] = None
    feelslike_c: Optional[int] = None
    uv_index: Optional[int] = None
    visibility_km: Optional[int] = None

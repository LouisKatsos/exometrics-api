from pydantic import BaseModel, ConfigDict, Field
from typing import Optional
from datetime import datetime


class MetricsEntryCreate(BaseModel):
    """Mirrors the JSON written by MetricsLogger.log()."""
    model_config = ConfigDict(populate_by_name=True)

    timestamp:   int             # epoch millis, as written by System.currentTimeMillis()
    hr:          int
    hrv:         float
    hrv_slope:   float = Field(alias='hrvSlope')
    distance_m:  int   = Field(alias='distanceM')
    duration_ms: int   = Field(alias='durationMs')
    calories:    int
    steps:       int


class PowerChangeEventCreate(BaseModel):
    """Mirrors the JSON written by MetricsLogger.logPowerChange()."""
    model_config = ConfigDict(populate_by_name=True)

    timestamp:          int
    old_power_percent:  Optional[int] = Field(default=None, alias='oldPowerPercent')
    new_power_percent:  int           = Field(alias='newPowerPercent')
    reason:             str
    hr:                 int
    hrv:                float
    hrv_slope:           float = Field(alias='hrvSlope')


class ModeChangeEventCreate(BaseModel):
    """Mirrors the JSON written by MetricsLogger.logModeChange()."""
    model_config = ConfigDict(populate_by_name=True)

    timestamp:  int
    old_mode:   Optional[str] = Field(default=None, alias='oldMode')
    new_mode:   str           = Field(alias='newMode')
    hr:         int


class MetricsEntryResponse(BaseModel):
    id:          str
    user_id:     str
    received_at: datetime  # server-side receipt time, distinct from the device timestamp
    timestamp:   int
    hr:          int
    hrv:         float
    hrv_slope:   float
    distance_m:  int
    duration_ms: int
    calories:    int
    steps:       int


class EventResponse(BaseModel):
    id:          str
    user_id:     str
    received_at: datetime
    timestamp:   int
    type:        str  # "power_change" | "mode_change"
    hr:          int
    hrv:         Optional[float] = None
    hrv_slope:   Optional[float] = None
    old_power_percent: Optional[int] = None
    new_power_percent: Optional[int] = None
    reason:      Optional[str] = None
    old_mode:    Optional[str] = None
    new_mode:    Optional[str] = None

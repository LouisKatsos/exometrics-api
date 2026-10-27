from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field

# Wide enough never to reject real data (a phone with a wrong clock still
# uploads); the upper bound only stops absurd values (year 2100).
MAX_TIMESTAMP_MS = 4_102_444_800_000
ENTRY_ID_PATTERN = r'^[A-Za-z0-9_-]+$'
PARTICIPANT_CODE_PATTERN = r'^[A-Z0-9-]+$'


class RecordBase(BaseModel):
    """Fields every record written by the app's MetricsLogger carries.

    username/sessionId were added in app 1.0 (Oct 2026); entryId, test and
    participantCode in app 1.1. All are optional so older app builds keep
    working. Unknown fields are ignored.
    """
    model_config = ConfigDict(populate_by_name=True)

    timestamp:        int           = Field(ge=0, le=MAX_TIMESTAMP_MS)  # epoch millis, System.currentTimeMillis()
    # The app caps usernames at 64 characters from 1.1; older builds had no
    # cap, so the server accepts up to 256 rather than reject their records.
    username:         Optional[str] = Field(default=None, max_length=256)
    # Random pseudonymous code the app generates once per install (e.g. EXO-4K7Q-9ZMD),
    # so data can be analysed without the free-text username.
    participant_code: Optional[str] = Field(default=None, alias='participantCode', max_length=32,
                                            pattern=PARTICIPANT_CODE_PATTERN)
    session_id:       Optional[int] = Field(default=None, alias='sessionId', ge=0)
    entry_id:         Optional[str] = Field(default=None, alias='entryId', max_length=64, pattern=ENTRY_ID_PATTERN)
    test:             bool          = False  # true only for the app's "Log Fake Metric" debug button


class MetricsEntryCreate(RecordBase):
    """Mirrors the JSON written by MetricsLogger.log()."""

    hr:          int           = Field(ge=0, le=300)
    hrv:         float         = Field(ge=0, le=5000, allow_inf_nan=False)
    hrv_slope:   float         = Field(alias='hrvSlope', ge=-1e6, le=1e6, allow_inf_nan=False)
    hrv_source:  Optional[str] = Field(default=None, alias='hrvSource', max_length=32)  # 'beat' | 'bpm_estimate'
    distance_m:  int           = Field(alias='distanceM', ge=0, le=10_000_000)
    duration_ms: int           = Field(alias='durationMs', ge=0, le=10_000_000_000)
    calories:    int           = Field(ge=0, le=1_000_000)
    steps:       int           = Field(ge=0, le=100_000_000)


class MetricsBatchCreate(BaseModel):
    """Body of POST /metrics/batch. Each entry is validated on its own, so one
    bad entry doesn't fail the others."""
    entries: List[Any] = Field(min_length=1)


class PowerChangeEventCreate(RecordBase):
    """Mirrors the JSON written by MetricsLogger.logPowerChange()."""

    old_power_percent: Optional[int] = Field(default=None, alias='oldPowerPercent', ge=-100, le=100)
    new_power_percent: int           = Field(alias='newPowerPercent', ge=-100, le=100)
    reason:            str           = Field(max_length=64)
    hr:                int           = Field(ge=0, le=300)
    hrv:               float         = Field(ge=0, le=5000, allow_inf_nan=False)
    hrv_slope:         float         = Field(alias='hrvSlope', ge=-1e6, le=1e6, allow_inf_nan=False)


class ModeChangeEventCreate(RecordBase):
    """Mirrors the JSON written by MetricsLogger.logModeChange()."""

    old_mode: Optional[str] = Field(default=None, alias='oldMode', max_length=32)
    new_mode: str           = Field(alias='newMode', max_length=32)
    hr:       int           = Field(ge=0, le=300)


class FeedbackCreate(RecordBase):
    """Mirrors the JSON written by MetricsLogger.logFeedback()."""

    text: str = Field(min_length=1, max_length=5000)


class MetricsEntryResponse(BaseModel):
    id:          str
    user_id:     str
    received_at: datetime  # server-side receipt time, distinct from the device timestamp
    timestamp:   int
    hr:          int
    hrv:         float
    hrv_slope:   float
    hrv_source:  Optional[str] = None
    distance_m:  int
    duration_ms: int
    calories:    int
    steps:       int
    username:    Optional[str] = None
    participant_code: Optional[str] = None
    session_id:  Optional[int] = None
    entry_id:    Optional[str] = None
    test:        bool = False


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
    username:    Optional[str] = None
    participant_code: Optional[str] = None
    session_id:  Optional[int] = None
    entry_id:    Optional[str] = None
    test:        bool = False


class FeedbackResponse(BaseModel):
    id:          str
    user_id:     str
    username:    Optional[str] = None
    participant_code: Optional[str] = None
    session_id:  Optional[int] = None
    received_at: datetime
    timestamp:   int
    text:        str
    entry_id:    Optional[str] = None
    test:        bool = False

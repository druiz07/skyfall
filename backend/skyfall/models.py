"""Data models shared across SKYFALL."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class OrbitalElements(BaseModel):
    """Mean orbital elements as consumed by SGP4 (same meaning as a TLE / GP record)."""

    model_config = ConfigDict(frozen=True)

    epoch: AwareDatetime
    inclination_deg: float = Field(ge=0.0, le=180.0)
    raan_deg: float = Field(ge=0.0, lt=360.0)
    eccentricity: float = Field(ge=0.0, lt=1.0)
    arg_perigee_deg: float = Field(ge=0.0, lt=360.0)
    mean_anomaly_deg: float = Field(ge=0.0, lt=360.0)
    mean_motion_rev_per_day: float = Field(gt=0.0)
    bstar: float = 0.0


class ReentryNotice(BaseModel):
    """A re-entry prediction: DECAY_EPOCH +- WINDOW minutes (TIP semantics)."""

    model_config = ConfigDict(frozen=True)

    norad_id: int
    name: str
    decay_epoch: AwareDatetime
    window_minutes: float = Field(ge=0.0)
    elements: OrbitalElements
    source: Literal["demo", "spacetrack"]
    # When the notice was issued (MSG_EPOCH; demo: now) and, real TIPs only,
    # the re-entry point it predicts (longitude in [-180, 180)).
    issued_at: AwareDatetime | None = None
    predicted_lat: float | None = None
    predicted_lon: float | None = None


# --- API responses -----------------------------------------------------------


class ReentrySummary(BaseModel):
    norad_id: int
    name: str
    decay_epoch: AwareDatetime
    window_minutes: float
    inclination_deg: float
    source: Literal["demo", "spacetrack"]
    issued_at: AwareDatetime | None = None
    predicted_lat: float | None = None
    predicted_lon: float | None = None
    # The newest notice is the confirmation: it already fell, at predicted_lat/lon.
    landed: bool = False


class RegionSummary(BaseModel):
    area_km2: float
    n_cells: int


class Cell(BaseModel):
    lat: float  # cell center
    lon: float
    p: float  # probability that a fragment lands in this cell
    region: Literal[90, 95, 99]  # smallest region containing the cell


class EasaClosure(BaseModel):
    """Today's precautionary strip (closure.py) on the same grid, to set beside the zone."""

    half_width_km: float
    area_km2: float
    # Share of run B fragments inside the strip. Run B never shaped the strip,
    # so this is a fair score; it is still the model's, not real re-entries.
    coverage: float
    cells: list[tuple[float, float]]  # closed cell centres [lat, lon]


class Corridor(BaseModel):
    norad_id: int
    n_samples: int
    n_failed: int
    n_fragments: int
    resolution_deg: float
    regions: dict[Literal["90", "95", "99"], RegionSummary]
    cells: list[Cell]  # only cells inside the 99 % region
    # Subsample of breakup points [lat, lon], for drawing the uncertain track.
    breakup_points: list[tuple[float, float]]
    easa: list[EasaClosure]  # one per EASA width, narrowest first


class ImpactPoint(BaseModel):
    lat: float
    lon: float
    # "tip": point published in the notice; "orbit": sub-satellite point at DECAY_EPOCH.
    source: Literal["tip", "orbit"]


class Track(BaseModel):
    norad_id: int
    start: AwareDatetime  # DECAY_EPOCH - WINDOW
    end: AwareDatetime  # DECAY_EPOCH + WINDOW
    step_seconds: int
    points: list[tuple[float, float]]  # [lat, lon] every step_seconds, start to end
    impact: ImpactPoint


class HistoryNotice(BaseModel):
    """One notice of an object's series, as the globe needs it for the timeline."""

    index: int  # position in the series, oldest = 0
    issued_at: AwareDatetime | None
    decay_epoch: AwareDatetime
    window_minutes: float
    predicted_lat: float | None = None
    predicted_lon: float | None = None


class Landing(BaseModel):
    """Where and when the object really came down (the confirmation notice)."""

    decay_epoch: AwareDatetime
    lat: float
    lon: float


class History(BaseModel):
    norad_id: int
    name: str
    # Forecasts only, oldest first; the "it is down" confirmation goes to `landed`.
    notices: list[HistoryNotice]
    landed: Landing | None = None


class ClosureOption(BaseModel):
    name: Literal["skyfall_90", "skyfall_95", "skyfall_99", "easa_70km", "easa_120km"]
    half_width_km: float | None  # None for SKYFALL (shape comes from the map)
    area_km2: float
    # Fraction of independently simulated fragments landing inside the closure.
    coverage: float
    # Closed area relative to SKYFALL 99 % (+60 = closes 60 % more sky).
    area_vs_skyfall_pct: float


class Comparison(BaseModel):
    norad_id: int
    window_minutes: float
    resolution_deg: float
    n_fragments_exam: int  # fragments of the independent run used for coverage
    closures: list[ClosureOption]

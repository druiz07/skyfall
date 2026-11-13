"""HTTP API for SKYFALL."""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import logging
import os
import threading
import time
from functools import lru_cache

import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from skyfall import __version__
from skyfall.closure import window_track
from skyfall.comparison import compute_comparison
from skyfall.corridor import Forecast, corridor_from_forecast, forecast
from skyfall.models import (
    Comparison,
    Corridor,
    History,
    HistoryNotice,
    ImpactPoint,
    Landing,
    ReentryNotice,
    ReentrySummary,
    Track,
)
from skyfall.orbit import ground_track
from skyfall.sources.demo import demo_history, demo_reentries
from skyfall.sources.spacetrack import REPO_ROOT, SpaceTrackClient, SpaceTrackError, select_client
from skyfall.validation import confirmation, is_confirmation

@asynccontextmanager
async def _lifespan(_: FastAPI):
    _start_warmup()
    yield


app = FastAPI(
    lifespan=_lifespan,
    title="SKYFALL",
    version=__version__,
    description="Probabilistic re-entry corridors vs. precautionary airspace closures.",
)

# uvicorn's logger, so warm-up progress shows in the API console.
_log = logging.getLogger("uvicorn.error")

# A point every 30 s (~230 km of track) is smooth enough on the globe: +-15 h = 3 601 points.
TRACK_DRAW_STEP_S = 30

# Zones of real notices are kept on disk: a +-23 h notice takes minutes to compute,
# and a notice never changes once issued. Local only, like the Space-Track cache.
ZONE_CACHE_DIR = REPO_ROOT / "data_local" / "zones"
# Bump when the zone engine changes, so zones drawn by an old engine are not served.
ZONE_CACHE_VERSION = 2

# Demo notices are anchored once at startup, so every endpoint sees the same epochs.
_STARTED_AT = datetime.now(timezone.utc)


@lru_cache(maxsize=1)
def _client() -> SpaceTrackClient | None:
    """Chosen once per process from SKYFALL_SOURCE and credentials (None = demo)."""
    return select_client()


def _notices() -> dict[int, ReentryNotice]:
    client = _client()
    notices = demo_reentries(_STARTED_AT) if client is None else client.latest_notices()
    return {n.norad_id: n for n in notices}


@app.exception_handler(SpaceTrackError)
def _space_track_unavailable(request: Request, exc: SpaceTrackError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


def _get_notice(norad_id: int) -> ReentryNotice:
    notice = _notices().get(norad_id)
    if notice is None:
        raise HTTPException(status_code=404, detail=f"No re-entry notice for NORAD {norad_id}")
    return notice


def _history_notices(norad_id: int) -> tuple[str, list[ReentryNotice], ReentryNotice | None]:
    """Name, forecast notices of one object (oldest first) and its confirmation if any.

    Works for any NORAD id, also objects that fell days ago and left the live list.
    """
    client = _client()
    notices = demo_history(norad_id, _STARTED_AT) if client is None else client.notice_history(norad_id)
    if not notices:
        raise HTTPException(status_code=404, detail=f"No re-entry notices for NORAD {norad_id}")
    landed = confirmation(notices)
    # A notice issued after its own DECAY_EPOCH reports a fall, it predicts nothing.
    forecasts = [n for n in notices if n.issued_at is None or n.issued_at < n.decay_epoch]
    forecasts.sort(key=lambda n: n.issued_at or n.decay_epoch)
    return notices[-1].name, forecasts, landed


# One lock per notice: a request that arrives while the warm-up (or another
# request) is computing the same zone waits for it instead of computing it again.
_notice_locks: dict[ReentryNotice, threading.RLock] = {}
_notice_locks_guard = threading.Lock()


def _lock_for(notice: ReentryNotice) -> threading.RLock:
    with _notice_locks_guard:
        return _notice_locks.setdefault(notice, threading.RLock())


# Results are keyed by the whole notice, not the NORAD id: a new TIP for the
# same object is a new key and gets recomputed.
# Runs A and B are shared by /corridor and /comparison: simulate them once.
@lru_cache(maxsize=32)
def _forecast_cached(notice: ReentryNotice) -> Forecast:
    return forecast(notice)


def _forecast(notice: ReentryNotice) -> Forecast:
    with _lock_for(notice):
        return _forecast_cached(notice)


@lru_cache(maxsize=32)
def _corridor_cached(notice: ReentryNotice) -> Corridor:
    return corridor_from_forecast(notice, _forecast(notice))


def _corridor(notice: ReentryNotice) -> Corridor:
    with _lock_for(notice):
        return _corridor_cached(notice)


def _stored_corridor(notice: ReentryNotice) -> Corridor:
    """_corridor, saved to / read from disk for real notices (demo ones move with startup)."""
    if notice.source != "spacetrack":
        return _corridor(notice)
    key = f"v{ZONE_CACHE_VERSION}" + notice.model_dump_json()
    key = hashlib.sha256(key.encode()).hexdigest()[:16]
    path = ZONE_CACHE_DIR / f"{notice.norad_id}_{key}.json"
    if path.exists():
        return Corridor.model_validate_json(path.read_text(encoding="utf-8"))
    corridor = _corridor(notice)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(corridor.model_dump_json(), encoding="utf-8")
    return corridor


@lru_cache(maxsize=32)
def _comparison(notice: ReentryNotice) -> Comparison:
    return compute_comparison(notice, fc=_forecast(notice))


@lru_cache(maxsize=32)
def _track(notice: ReentryNotice) -> Track:
    lat, lon = window_track(notice, margin_min=0, step_s=TRACK_DRAW_STEP_S)
    if notice.predicted_lat is not None and notice.predicted_lon is not None:
        impact = ImpactPoint(lat=notice.predicted_lat, lon=notice.predicted_lon, source="tip")
    else:
        at_decay = ground_track(notice.elements, notice.decay_epoch, np.zeros(1))
        impact = ImpactPoint(
            lat=float(at_decay.lat_deg[0]), lon=float(at_decay.lon_deg[0]), source="orbit"
        )
    window = timedelta(minutes=notice.window_minutes)
    return Track(
        norad_id=notice.norad_id,
        start=notice.decay_epoch - window,
        end=notice.decay_epoch + window,
        step_seconds=TRACK_DRAW_STEP_S,
        points=[(round(float(a), 3), round(float(o), 3)) for a, o in zip(lat, lon)],
        impact=impact,
    )


def _demo_warmup_notices() -> list[ReentryNotice]:
    """Every demo notice the web can ask a zone for, quickest (narrowest window) first."""
    notices = {n for n in _notices().values()}
    for norad_id in list({n.norad_id for n in notices}):
        notices.update(demo_history(norad_id, _STARTED_AT))
    return sorted(notices, key=lambda n: (n.window_minutes, n.decay_epoch))


def _warm_demo_zones() -> None:
    for notice in _demo_warmup_notices():
        start = time.perf_counter()
        try:
            _stored_corridor(notice)
        except Exception:
            _log.exception("warm-up: zone %s failed", notice.norad_id)
            continue
        _log.info(
            "warm-up: zone %s +-%g min ready (%.0f s)",
            notice.norad_id,
            notice.window_minutes,
            time.perf_counter() - start,
        )
    _log.info("warm-up: all demo zones ready")


def _start_warmup() -> None:
    """Demo only: compute every zone in the background, so the first click is instant.

    Real zones are kept on disk instead (scripts/precompute_history.py). SKYFALL_WARMUP=0 turns it off.
    """
    if _client() is not None or os.environ.get("SKYFALL_WARMUP", "1") == "0":
        return
    threading.Thread(target=_warm_demo_zones, name="demo-warmup", daemon=True).start()


@app.get("/health")
def health() -> dict[str, str]:
    source = "demo" if _client() is None else "spacetrack"
    return {"status": "ok", "version": __version__, "source": source}


@app.get("/reentries")
def list_reentries() -> list[ReentrySummary]:
    return [
        ReentrySummary(
            norad_id=n.norad_id,
            name=n.name,
            decay_epoch=n.decay_epoch,
            window_minutes=n.window_minutes,
            inclination_deg=n.elements.inclination_deg,
            source=n.source,
            issued_at=n.issued_at,
            predicted_lat=n.predicted_lat,
            predicted_lon=n.predicted_lon,
            landed=is_confirmation(n),
        )
        for n in _notices().values()
    ]


@app.get("/reentries/{norad_id}/corridor")
def get_corridor(norad_id: int) -> Corridor:
    return _stored_corridor(_get_notice(norad_id))


@app.get("/reentries/{norad_id}/track")
def get_track(norad_id: int) -> Track:
    """Ground track across the notice window, for drawing on the globe."""
    return _track(_get_notice(norad_id))


@app.get("/reentries/{norad_id}/comparison")
def get_comparison(norad_id: int) -> Comparison:
    """SKYFALL 99 % zone vs EASA 70 / 120 km strips: area and independent coverage."""
    return _comparison(_get_notice(norad_id))


@app.get("/reentries/{norad_id}/history")
def get_history(norad_id: int) -> History:
    """Every notice of one object, oldest first, plus where it really fell if known."""
    name, forecasts, landed = _history_notices(norad_id)
    return History(
        norad_id=norad_id,
        name=name,
        notices=[
            HistoryNotice(
                index=i,
                issued_at=n.issued_at,
                decay_epoch=n.decay_epoch,
                window_minutes=n.window_minutes,
                predicted_lat=n.predicted_lat,
                predicted_lon=n.predicted_lon,
            )
            for i, n in enumerate(forecasts)
        ],
        landed=None
        if landed is None
        else Landing(decay_epoch=landed.decay_epoch, lat=landed.predicted_lat, lon=landed.predicted_lon),
    )


def _history_notice(norad_id: int, index: int) -> ReentryNotice:
    _, forecasts, _ = _history_notices(norad_id)
    if not 0 <= index < len(forecasts):
        raise HTTPException(status_code=404, detail=f"NORAD {norad_id} has no notice {index}")
    return forecasts[index]


@app.get("/reentries/{norad_id}/history/{index}/corridor")
def get_history_corridor(norad_id: int, index: int) -> Corridor:
    """Zone of one notice of the series (index as in /history)."""
    return _stored_corridor(_history_notice(norad_id, index))


@app.get("/reentries/{norad_id}/history/{index}/track")
def get_history_track(norad_id: int, index: int) -> Track:
    """Ground track of one notice of the series."""
    return _track(_history_notice(norad_id, index))

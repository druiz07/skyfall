"""Space-Track.org client: cookie login, local cache with TTL, rate limiting.

Space-Track's user agreement forbids redistributing its data, so responses
are cached only under data_local/ (git-ignored) and never ship with the repo.
Its limits are ~30 requests/min and 300/hour: the client spaces requests
2.5 s apart and refuses to go past a lower hourly budget instead of looping.
"""

import hashlib
import json
import logging
import math
import os
import time
import urllib.parse
import urllib.request
from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from http.cookiejar import CookieJar
from pathlib import Path

from skyfall.models import OrbitalElements, ReentryNotice

log = logging.getLogger(__name__)

BASE_URL = "https://www.space-track.org"
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CACHE_DIR = REPO_ROOT / "data_local" / "spacetrack"

# Cache lifetimes (s): TIPs update every few hours near re-entry, elements a
# few times a day, confirmed decays never change.
TTL_TIP_S = 3600.0
TTL_GP_S = 6 * 3600.0
TTL_DECAY_S = 24 * 3600.0

MIN_INTERVAL_S = 2.5  # <= 24 req/min, under the 30/min limit
MAX_PER_HOUR = 200  # wide margin under the 300/hour limit, shared by every process

# How far before a notice to look for its orbital elements.
GP_LOOKBACK = timedelta(days=3)


class SpaceTrackError(RuntimeError):
    pass


class RateLimiter:
    """Waits to keep requests MIN_INTERVAL_S apart; refuses past MAX_PER_HOUR.

    Space-Track counts the hour per account, not per process. With log_path,
    request times are kept in a file so a new run knows what earlier runs spent.
    """

    def __init__(
        self,
        min_interval_s: float = MIN_INTERVAL_S,
        max_per_hour: int = MAX_PER_HOUR,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        log_path: Path | None = None,
    ):
        self.min_interval_s = min_interval_s
        self.max_per_hour = max_per_hour
        self._clock, self._sleep = clock, sleep
        self._log_path = log_path
        self._recent: deque[float] = deque()
        if log_path is not None and log_path.exists():
            now = clock()
            self._recent.extend(
                t
                for t in map(float, log_path.read_text(encoding="utf-8").split())
                if now - t < 3600.0
            )

    def acquire(self) -> None:
        now = self._clock()
        while self._recent and now - self._recent[0] >= 3600.0:
            self._recent.popleft()
        if len(self._recent) >= self.max_per_hour:
            raise SpaceTrackError(
                f"Hourly budget of {self.max_per_hour} Space-Track requests used up; "
                "try again later (cached data still works)."
            )
        if self._recent and now - self._recent[-1] < self.min_interval_s:
            self._sleep(self.min_interval_s - (now - self._recent[-1]))
            now = self._clock()
        self._recent.append(now)
        if self._log_path is not None:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log_path.write_text(
                "".join(f"{t:.3f}\n" for t in self._recent), encoding="utf-8"
            )


def read_env() -> dict[str, str]:
    """Settings from .env, overridden by the real environment."""
    return {**load_env(), **os.environ}


def select_client(env: dict[str, str] | None = None) -> "SpaceTrackClient | None":
    """Space-Track client, or None for demo mode, according to SKYFALL_SOURCE.

    auto (default): Space-Track if credentials exist, demo otherwise.
    demo: always demo (tests, offline videos). spacetrack: credentials required.
    """
    env = read_env() if env is None else env
    mode = env.get("SKYFALL_SOURCE", "auto").strip().lower() or "auto"
    if mode == "demo":
        return None
    if mode not in ("auto", "spacetrack"):
        raise ValueError(f"SKYFALL_SOURCE must be auto, demo or spacetrack, not {mode!r}")
    client = SpaceTrackClient.from_env(env)
    if client is None and mode == "spacetrack":
        raise SpaceTrackError("SKYFALL_SOURCE=spacetrack but SPACETRACK_USER / PASSWORD are missing")
    return client


def load_env(path: Path = REPO_ROOT / ".env") -> dict[str, str]:
    """KEY=value lines from .env (no dependency on python-dotenv)."""
    if not path.exists():
        return {}
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip("\"'")
    return env


class SpaceTrackClient:
    def __init__(
        self,
        user: str,
        password: str,
        cache_dir: Path = DEFAULT_CACHE_DIR,
        limiter: RateLimiter | None = None,
        opener: urllib.request.OpenerDirector | None = None,
        wall_clock: Callable[[], float] = time.time,
    ):
        self._user, self._password = user, password
        self.cache_dir = cache_dir
        self._limiter = limiter or RateLimiter(log_path=cache_dir / "requests.log")
        # The session cookie lives only in this in-memory jar.
        self._opener = opener or urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(CookieJar())
        )
        self._wall_clock = wall_clock
        self._logged_in = False

    def tip_history(self, norad_id: int) -> list[dict]:
        """Every TIP notice for one object, oldest first."""
        return self.query(
            f"class/tip/NORAD_CAT_ID/{norad_id}/orderby/MSG_EPOCH%20asc", TTL_TIP_S
        )

    def gp_history(self, norad_id: int, start: datetime, end: datetime) -> list[dict]:
        """Element sets with EPOCH between the days of start and end (inclusive)."""
        span = f"{start:%Y-%m-%d}--{end + timedelta(days=1):%Y-%m-%d}"
        return self.query(
            f"class/gp_history/NORAD_CAT_ID/{norad_id}/EPOCH/{span}/orderby/EPOCH%20asc",
            TTL_GP_S,
        )

    def notice_history(self, norad_id: int) -> list[ReentryNotice]:
        """All TIPs of one object as notices, each with elements known when it was issued.

        Two requests in total: the TIP series and one gp_history span covering it.
        """
        tips = self.tip_history(norad_id)
        if not tips:
            return []
        issued = [parse_utc(t["MSG_EPOCH"]) for t in tips]
        gp_rows = self.gp_history(norad_id, min(issued) - GP_LOOKBACK, max(issued))
        return [notice_from_tip(t, gp_rows) for t in tips]

    def latest_notices(self) -> list[ReentryNotice]:
        """The newest TIP of every object whose re-entry is not over yet (or just was)."""
        tips = self.query("class/tip/DECAY_EPOCH/%3Enow-1/orderby/MSG_EPOCH%20desc", TTL_TIP_S)
        newest: dict[int, dict] = {}
        for tip in tips:  # newest first, so the first one per object wins
            newest.setdefault(int(tip["NORAD_CAT_ID"]), tip)
        notices = []
        for norad_id, tip in newest.items():
            issued = parse_utc(tip["MSG_EPOCH"])
            gp_rows = self.gp_history(norad_id, issued - GP_LOOKBACK, issued)
            notices.append(notice_from_tip(tip, gp_rows))
        return sorted(notices, key=lambda n: n.decay_epoch)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None, **kwargs) -> "SpaceTrackClient | None":
        """Client from SPACETRACK_USER / SPACETRACK_PASSWORD, or None (demo mode)."""
        env = read_env() if env is None else env
        user, password = env.get("SPACETRACK_USER"), env.get("SPACETRACK_PASSWORD")
        return cls(user, password, **kwargs) if user and password else None

    def query(self, path: str, ttl_s: float) -> list[dict]:
        """GET /basicspacedata/query/<path>/format/json, served from cache when fresh.

        If Space-Track cannot answer, an expired cache entry is better than nothing.
        """
        cached = self._read_cache(path, ttl_s)
        if cached is not None:
            return cached
        try:
            if not self._logged_in:
                self._login()
            url = f"{BASE_URL}/basicspacedata/query/{path}/format/json"
            data = json.loads(self._request(urllib.request.Request(url)))
            # Refusals (e.g. the rate limit) come back as 200 + [{"error": ...}].
            # They must never be cached as if they were data.
            if isinstance(data, dict):
                data = [data]
            if data and isinstance(data[0], dict) and "error" in data[0]:
                raise SpaceTrackError(f"Space-Track refused the query: {data[0]['error']}")
        except SpaceTrackError as exc:
            stale = self._read_cache(path, math.inf)
            if stale is None:
                raise
            log.warning("%s; serving expired cache for %s", exc, path)
            return stale
        self._write_cache(path, data)
        return data

    def _login(self) -> None:
        form = urllib.parse.urlencode({"identity": self._user, "password": self._password})
        body = self._request(
            urllib.request.Request(f"{BASE_URL}/ajaxauth/login", data=form.encode(), method="POST")
        )
        # A bad password still answers 200, with {"Login":"Failed"}.
        if "failed" in body.lower():
            raise SpaceTrackError("Space-Track login failed: check SPACETRACK_USER / PASSWORD")
        self._logged_in = True

    def _request(self, request: urllib.request.Request) -> str:
        self._limiter.acquire()
        try:
            with self._opener.open(request, timeout=60) as response:
                return response.read().decode("utf-8")
        except OSError as exc:  # URLError / HTTPError / timeouts
            raise SpaceTrackError(f"Space-Track request failed: {exc}") from exc

    def _cache_file(self, path: str) -> Path:
        return self.cache_dir / f"{hashlib.sha256(path.encode()).hexdigest()[:24]}.json"

    def _read_cache(self, path: str, ttl_s: float) -> list[dict] | None:
        file = self._cache_file(path)
        if not file.exists():
            return None
        entry = json.loads(file.read_text(encoding="utf-8"))
        if self._wall_clock() - entry["fetched_at"] > ttl_s:
            return None
        return entry["data"]

    def _write_cache(self, path: str, data: list[dict]) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        entry = {"path": path, "fetched_at": self._wall_clock(), "data": data}
        self._cache_file(path).write_text(json.dumps(entry), encoding="utf-8")


# --- Space-Track records -> SKYFALL models -------------------------------------


def parse_utc(text: str) -> datetime:
    """Space-Track timestamps ('2026-10-04 15:16:00' or ISO with 'T'), always UTC."""
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


def parse_gp(row: dict) -> OrbitalElements:
    """One GP / gp_history record (OMM fields, strings) -> OrbitalElements."""
    return OrbitalElements(
        epoch=parse_utc(row["EPOCH"]),
        inclination_deg=float(row["INCLINATION"]),
        raan_deg=float(row["RA_OF_ASC_NODE"]) % 360.0,
        eccentricity=float(row["ECCENTRICITY"]),
        arg_perigee_deg=float(row["ARG_OF_PERICENTER"]) % 360.0,
        mean_anomaly_deg=float(row["MEAN_ANOMALY"]) % 360.0,
        mean_motion_rev_per_day=float(row["MEAN_MOTION"]),
        bstar=float(row["BSTAR"]),
    )


def pick_elements(gp_rows: list[dict], issued_at: datetime) -> dict:
    """Newest element set that already existed when a notice was issued.

    Nothing from the future: the orbit snapshot (EPOCH) must be before the
    notice, and so must its publication (CREATION_DATE), which can lag the
    snapshot by hours.
    """
    known = [
        row
        for row in gp_rows
        if parse_utc(row["EPOCH"]) < issued_at and parse_utc(row["CREATION_DATE"]) <= issued_at
    ]
    if not known:
        raise SpaceTrackError(f"No element set published before {issued_at:%Y-%m-%d %H:%M} UTC")
    return max(known, key=lambda row: parse_utc(row["EPOCH"]))


def notice_from_tip(tip: dict, gp_rows: list[dict]) -> ReentryNotice:
    """TIP record + the object's element history -> ReentryNotice."""
    issued_at = parse_utc(tip["MSG_EPOCH"])
    gp = pick_elements(gp_rows, issued_at)
    lat = float(tip["LAT"]) if tip.get("LAT") is not None else None
    lon = float(tip["LON"]) if tip.get("LON") is not None else None
    if lon is not None and lon >= 180.0:  # TIP longitudes come in [0, 360)
        lon = round(lon - 360.0, 6)
    return ReentryNotice(
        norad_id=int(tip["NORAD_CAT_ID"]),
        name=gp.get("OBJECT_NAME") or f"NORAD {tip['NORAD_CAT_ID']}",
        decay_epoch=parse_utc(tip["DECAY_EPOCH"]),
        window_minutes=float(tip["WINDOW"]),
        elements=parse_gp(gp),
        source="spacetrack",
        issued_at=issued_at,
        predicted_lat=lat,
        predicted_lon=lon,
    )

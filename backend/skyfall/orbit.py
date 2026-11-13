"""Orbit propagation (SGP4) and conversion to latitude / longitude.

Pipeline:
    orbital elements -> SGP4 -> position in TEME (a frame fixed to the stars,
    it does not turn with the Earth) -> rotate by the Earth's sidereal angle
    (GMST) -> Earth-fixed position -> latitude / longitude / altitude (WGS84).

Simplifications (sub-km to few-km effect, negligible next to re-entry
uncertainty): UTC is used as UT1 and polar motion is ignored.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
from sgp4.api import WGS72, Satrec, jday

from skyfall.models import OrbitalElements

MINUTES_PER_DAY = 1440.0

_SGP4_EPOCH_ORIGIN = datetime(1949, 12, 31, tzinfo=timezone.utc)
_WGS84_A_KM = 6378.137
_WGS84_F = 1.0 / 298.257223563
_WGS84_E2 = _WGS84_F * (2.0 - _WGS84_F)


@dataclass(frozen=True)
class GroundTrack:
    lat_deg: np.ndarray
    lon_deg: np.ndarray  # wrapped to [-180, 180)
    alt_km: np.ndarray
    ok: np.ndarray  # False where SGP4 reported an error


def to_julian(t: datetime) -> tuple[float, float]:
    """Split Julian date (day part, fraction) as used by sgp4."""
    t = t.astimezone(timezone.utc)
    return jday(t.year, t.month, t.day, t.hour, t.minute, t.second + t.microsecond / 1e6)


def build_satrec(el: OrbitalElements) -> Satrec:
    sat = Satrec()
    sat.sgp4init(
        WGS72,
        "i",
        0,
        (el.epoch - _SGP4_EPOCH_ORIGIN).total_seconds() / 86400.0,
        el.bstar,
        0.0,
        0.0,
        el.eccentricity,
        np.radians(el.arg_perigee_deg),
        np.radians(el.inclination_deg),
        np.radians(el.mean_anomaly_deg),
        el.mean_motion_rev_per_day * 2.0 * np.pi / MINUTES_PER_DAY,
        np.radians(el.raan_deg),
    )
    return sat


def gmst_rad(jd: np.ndarray | float, fr: np.ndarray | float) -> np.ndarray:
    """Greenwich mean sidereal time (IAU 1982): how far Earth has turned."""
    t = ((np.asarray(jd) - 2451545.0) + np.asarray(fr)) / 36525.0
    seconds = (
        67310.54841
        + (876600.0 * 3600.0 + 8640184.812866) * t
        + 0.093104 * t**2
        - 6.2e-6 * t**3
    )
    return np.radians((seconds % 86400.0) / 240.0)


def teme_to_ecef(r_teme: np.ndarray, gmst: np.ndarray) -> np.ndarray:
    c, s = np.cos(gmst), np.sin(gmst)
    x, y, z = r_teme[:, 0], r_teme[:, 1], r_teme[:, 2]
    return np.column_stack((c * x + s * y, -s * x + c * y, z))


def ecef_to_geodetic(r_ecef: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Earth-fixed km -> (lat deg, lon deg, alt km) on the WGS84 ellipsoid."""
    x, y, z = r_ecef[:, 0], r_ecef[:, 1], r_ecef[:, 2]
    lon = np.arctan2(y, x)
    p = np.hypot(x, y)
    lat = np.arctan2(z, p * (1.0 - _WGS84_E2))
    for _ in range(5):
        sin_lat = np.sin(lat)
        n = _WGS84_A_KM / np.sqrt(1.0 - _WGS84_E2 * sin_lat**2)
        alt = p * np.cos(lat) + z * sin_lat - _WGS84_A_KM * np.sqrt(1.0 - _WGS84_E2 * sin_lat**2)
        lat = np.arctan2(z, p * (1.0 - _WGS84_E2 * n / (n + alt)))
    sin_lat = np.sin(lat)
    alt = p * np.cos(lat) + z * sin_lat - _WGS84_A_KM * np.sqrt(1.0 - _WGS84_E2 * sin_lat**2)
    return np.degrees(lat), np.degrees(lon), alt


def ground_track(el: OrbitalElements, t0: datetime, offsets_min: np.ndarray) -> GroundTrack:
    """Sub-satellite points at t0 + offsets (minutes)."""
    offsets = np.ascontiguousarray(offsets_min, dtype=np.float64)
    jd0, fr0 = to_julian(t0)
    jd = np.full_like(offsets, jd0)
    fr = fr0 + offsets / MINUTES_PER_DAY

    errors, r_teme, _ = build_satrec(el).sgp4_array(jd, fr)
    lat, lon, alt = ecef_to_geodetic(teme_to_ecef(r_teme, gmst_rad(jd, fr)))
    lon = (lon + 180.0) % 360.0 - 180.0
    return GroundTrack(lat_deg=lat, lon_deg=lon, alt_km=alt, ok=errors == 0)

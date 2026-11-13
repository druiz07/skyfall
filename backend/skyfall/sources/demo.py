"""Synthetic re-entries generated in code, so SKYFALL runs without credentials.

The orbits are invented (no Space-Track data). They mimic the kind of TIP
notices seen in practice: a Starlink-like object with a tight final window,
a sun-synchronous one with +-5 h, and a Starlink-like one with +-15 h.
DEMO-1 also has an invented series of earlier notices (demo_history).

Orbits are circular at DEMO_ALTITUDE_KM with no drag (bstar = 0): SGP4 is only
used for the shape of the ground track, the re-entry time comes from the notice.
"""

from datetime import datetime, timedelta, timezone

import numpy as np

from skyfall.models import OrbitalElements, ReentryNotice

DEMO_ALTITUDE_KM = 200.0
# Age of the orbital elements when the notice is issued. Real notices use
# elements a few hours old (46698: 0.9-22.5 h), and that age sets how far the
# track may have drifted sideways (track_drift.py).
DEMO_ELEMENTS_AGE = timedelta(hours=2)
_EARTH_RADIUS_KM = 6378.137
_EARTH_MU_KM3_S2 = 398600.4418
_J2 = 1.08262668e-3

# (norad_id, name, hours after reference, window +- min, inclination, raan, mean anomaly)
_SCENARIOS = (
    (900001, "DEMO-1 Starlink-like (53 deg, +-43 min)", 3, 43.0, 53.0, 120.0, 10.0),
    (900002, "DEMO-2 Sun-synchronous (97.6 deg, +-5 h)", 21, 300.0, 97.6, 250.0, 200.0),
    (900003, "DEMO-3 Starlink-like (53 deg, +-15 h)", 66, 900.0, 53.0, 30.0, 300.0),
)


# Invented notice series for DEMO-1, oldest first, the last one being the live
# notice above: (hours before reference it was issued, window +- min, minutes its
# DECAY_EPOCH sits from the final one). Real series wander like this (46698).
_DEMO_1_HISTORY = (
    (-66, 900.0, 50),
    (-21, 300.0, -30),
    (-8, 120.0, 20),
    (-3, 60.0, -10),
    (0, 43.0, 0),
)


def _mean_motion_rev_per_day(altitude_km: float) -> float:
    a = _EARTH_RADIUS_KM + altitude_km
    return np.sqrt(_EARTH_MU_KM3_S2 / a**3) * 86400.0 / (2.0 * np.pi)


def _rewound(el: OrbitalElements, shift: timedelta) -> OrbitalElements:
    """The same orbit described at epoch + shift (J2 drift of node and in-orbit angle).

    Good to ~2 km per hour of shift along the track, like real elements a bit off.
    """
    a = _EARTH_RADIUS_KM + DEMO_ALTITUDE_KM
    k = _J2 * (_EARTH_RADIUS_KM / a) ** 2
    cos_i = np.cos(np.radians(el.inclination_deg))
    rev_deg = 360.0 * el.mean_motion_rev_per_day  # degrees per day
    raan_rate = -1.5 * k * cos_i * rev_deg
    angle_rate = rev_deg * (1 + 0.75 * k * (3 * cos_i**2 - 1) + 0.75 * k * (5 * cos_i**2 - 1))
    days = shift.total_seconds() / 86400.0
    return el.model_copy(
        update={
            "epoch": el.epoch + shift,
            "raan_deg": float((el.raan_deg + raan_rate * days) % 360.0),
            "mean_anomaly_deg": float((el.mean_anomaly_deg + angle_rate * days) % 360.0),
        }
    )


def demo_reentries(reference: datetime | None = None) -> list[ReentryNotice]:
    """Demo notices placed a few hours / days after `reference` (default: now, UTC)."""
    ref = (reference or datetime.now(timezone.utc)).replace(second=0, microsecond=0)
    mean_motion = _mean_motion_rev_per_day(DEMO_ALTITUDE_KM)

    notices = []
    for norad_id, name, hours, window, inclination, raan, mean_anomaly in _SCENARIOS:
        decay_epoch = ref + timedelta(hours=hours)
        elements = OrbitalElements(
            epoch=ref - DEMO_ELEMENTS_AGE,
            inclination_deg=inclination,
            raan_deg=raan,
            eccentricity=0.0001,
            arg_perigee_deg=0.0,
            mean_anomaly_deg=mean_anomaly,
            mean_motion_rev_per_day=mean_motion,
        )
        notices.append(
            ReentryNotice(
                norad_id=norad_id,
                name=name,
                decay_epoch=decay_epoch,
                window_minutes=window,
                elements=elements,
                source="demo",
                # Issued now: leads of 3 h, 21 h and 66 h use three different
                # rows of the TIP error table.
                issued_at=ref,
            )
        )
    return notices


def demo_history(norad_id: int, reference: datetime | None = None) -> list[ReentryNotice]:
    """Every notice of one demo object, oldest first (DEMO-1 has a series, others one)."""
    live = {n.norad_id: n for n in demo_reentries(reference)}.get(norad_id)
    if live is None:
        return []
    if norad_id != 900001:
        return [live]
    final_decay = live.decay_epoch
    notices = []
    for hours, window, decay_shift_min in _DEMO_1_HISTORY:
        shift = timedelta(hours=hours)
        notices.append(
            live.model_copy(
                update={
                    "decay_epoch": final_decay + timedelta(minutes=decay_shift_min),
                    "window_minutes": window,
                    "elements": _rewound(live.elements, shift),
                    "issued_at": live.issued_at + shift,
                }
            )
        )
    return notices

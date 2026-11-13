"""SKYFALL 90/95/99 % zones vs today's precautionary closures: area and coverage.

Coverage is scored on run C, independent of the runs that drew the SKYFALL zone
(A ranks cells, B sets the boundary; see corridor.forecast). Scoring the zone
on fragments it was drawn around would be marking our own exam. A fresh run
grades all closures equally.
"""

from dataclasses import replace

from skyfall.closure import EASA_HALF_WIDTHS_KM, precautionary_mask, window_track
from skyfall.config import DispersionConfig, GridConfig, MonteCarloConfig
from skyfall.corridor import LEVELS, Forecast, forecast, simulate
from skyfall.density import cell_areas_km2
from skyfall.models import ClosureOption, Comparison, ReentryNotice

# Run C seed = run A seed + this offset (B uses corridor.CALIB_SEED_OFFSET).
EXAM_SEED_OFFSET = 2_000


def compute_comparison(
    notice: ReentryNotice,
    mc: MonteCarloConfig = MonteCarloConfig(),
    dispersion: DispersionConfig = DispersionConfig(),
    grid: GridConfig = GridConfig(),
    fc: Forecast | None = None,
) -> Comparison:
    """fc: runs A and B, if already computed (e.g. cached for /corridor)."""
    fc = fc or forecast(notice, mc, dispersion, grid)
    exam = simulate(notice, replace(mc, seed=mc.seed + EXAM_SEED_OFFSET), dispersion, grid)
    res = fc.rank.density.resolution_deg
    areas = cell_areas_km2(res)

    masks = {f"skyfall_{level}": (None, fc.masks[level]) for level in LEVELS}
    lat, lon = window_track(notice)
    for w in EASA_HALF_WIDTHS_KM:
        masks[f"easa_{w:.0f}km"] = (w, precautionary_mask(lat, lon, w, res))

    skyfall_area = float(areas[masks["skyfall_99"][1]].sum())
    closures = []
    for name, (half_width, mask) in masks.items():
        area = float(areas[mask].sum())
        closures.append(
            ClosureOption(
                name=name,
                half_width_km=half_width,
                area_km2=area,
                coverage=exam.density.coverage(mask),
                area_vs_skyfall_pct=100.0 * (area / skyfall_area - 1.0),
            )
        )

    return Comparison(
        norad_id=notice.norad_id,
        window_minutes=notice.window_minutes,
        resolution_deg=res,
        n_fragments_exam=exam.n_fragments,
        closures=closures,
    )

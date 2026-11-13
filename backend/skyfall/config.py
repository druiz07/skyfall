"""Tunable parameters, with documented defaults."""

from dataclasses import dataclass
from typing import Literal

TimeDistribution = Literal["empirical", "uniform", "normal"]


@dataclass(frozen=True)
class MonteCarloConfig:
    # Number of simulated re-entry instants. None = scale with the window.
    n_samples: int | None = None
    # Wide windows spread fragments over a huge area: with too few samples the
    # sparse edges of the 99 % region go missing and its area comes out too
    # small (+-15 h: 48 M km2 with 10k samples vs ~82 M km2 converged).
    # The calibrated regions (density.calibrated_region_mask) never cheat on
    # coverage, but a noisy ranking costs area instead: +-5 h is 14 % too big
    # at 100 samples per window minute. 400 is within ~1.5 % of 16x that.
    samples_per_window_minute: float = 400.0
    min_samples: int = 80_000
    # The empirical time spread can reach days. After ~1 day of orbits the
    # tracks fill the whole latitude band and the area stops growing, so the
    # sample count does not need to keep growing either.
    max_samples: int = 1_000_000
    # Ranking run (run A): one breakup instant every `rank_step_seconds`,
    # weighted by its probability, no randomness (~37 km of ground track).
    # Demo +-5 h, 99 % area: 20 s 156 M | 10 s 136.5 M | 5 s 133.3 M |
    # 2.5 s 133.1 M km2.
    rank_step_seconds: float = 5.0
    # Fixed seed so every run (and every test) is reproducible.
    seed: int = 42
    # How re-entry instants are spread around DECAY_EPOCH.
    # "empirical" (default): errors of past TIPs with the same lead time
    #   (tip_errors.py). Real re-entries fall outside +- WINDOW ~15 % of the time.
    # "uniform": every minute of +- WINDOW equally likely, nothing outside.
    # "normal": more weight near DECAY_EPOCH (sigma = WINDOW / 2, truncated).
    time_distribution: TimeDistribution = "empirical"

    def samples_for(self, spread_minutes: float) -> int:
        """Samples for re-entry instants spread over +-spread_minutes."""
        if self.n_samples is not None:
            return self.n_samples
        wanted = round(2 * spread_minutes * self.samples_per_window_minute)
        return min(self.max_samples, max(self.min_samples, wanted))


@dataclass(frozen=True)
class DispersionConfig:
    """Where fragments land relative to the breakup point.

    After breakup (~80 km up) fragments keep flying forward along the ground
    track (along-track) and barely spread sideways (cross-track): the footprint
    is a long, thin strip. Values are order-of-magnitude assumptions, not an
    aerodynamic model; heavy dense parts go further, light ones fall short.
    """

    # Mean and spread of the forward distance travelled (km). Clipped at 0.
    along_mean_km: float = 800.0
    along_sigma_km: float = 400.0
    # Sideways spread (km).
    cross_sigma_km: float = 25.0
    # Add the sideways drift of the notice's (aging) elements to
    # cross_sigma_km (track_drift.py). Off = fragments' own spread only.
    track_drift: bool = True
    # Fragments simulated per breakup sample.
    fragments_per_sample: int = 4
    # Expected footprint (the ranking run spreads it instead of random
    # fragments): along-track nodes every `footprint_along_step_km`, under a
    # cell (~55 km) so no cell is skipped, out to mean + 4 sigma; cross-track
    # nodes every `footprint_cross_step_km` (half a cell) out to +-4 sigma.
    # A fixed node count left empty stripes between nodes once the track
    # drift widened the strip to 80-180 km, and the ranking run then closed
    # far too much sky (demo +-43 min, 90 % zone: 105 M km2 instead of 15 M).
    footprint_along_step_km: float = 50.0
    footprint_cross_step_km: float = 25.0


@dataclass(frozen=True)
class GridConfig:
    # Cell size of the probability map (0.5 deg ~ 55 km at the equator).
    resolution_deg: float = 0.5

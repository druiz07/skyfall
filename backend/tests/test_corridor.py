from datetime import datetime, timezone

import numpy as np
import pytest

from skyfall.config import MonteCarloConfig
from skyfall.corridor import compute_corridor, forecast
from skyfall.sources.demo import demo_reentries

REF = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


def _notice(norad_id):
    return next(n for n in demo_reentries(REF) if n.norad_id == norad_id)


def test_default_ranking_step_has_converged():
    # +-5 h with empirical tails: halving the ranking grid step (and another
    # seed for the random run B) must give nearly the same 99 % area.
    notice = _notice(900002)
    auto = compute_corridor(notice)
    step = MonteCarloConfig().rank_step_seconds
    fine = compute_corridor(notice, mc=MonteCarloConfig(rank_step_seconds=step / 2, seed=1))

    assert auto.regions["99"].area_km2 == pytest.approx(fine.regions["99"].area_km2, rel=0.03)


def test_ranking_run_does_not_depend_on_the_seed():
    # Run A has no randomness: only run B (the boundary) changes with the seed.
    notice = _notice(900001)
    a = forecast(notice, MonteCarloConfig(seed=1))
    b = forecast(notice, MonteCarloConfig(seed=2))

    np.testing.assert_array_equal(a.rank.density.prob, b.rank.density.prob)
    assert not np.array_equal(a.calib.density.prob, b.calib.density.prob)

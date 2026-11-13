"""TIP error table: invented notices only, no Space-Track data."""

import numpy as np
import pytest

from skyfall.tip_errors import (
    LEAD_LABELS,
    TABLE_PATH,
    TipError,
    TipErrorModel,
    lead_bucket,
    quantile_table,
    tip_errors,
)


def _tip(norad, issued, predicted, window):
    return {
        "NORAD_CAT_ID": str(norad),
        "MSG_EPOCH": issued,
        "DECAY_EPOCH": predicted,
        "WINDOW": str(window),
    }


def test_lead_buckets():
    assert [lead_bucket(h) for h in (-2, 0, 5.9, 6, 23, 24, 71, 72, 500)] == [
        0, 0, 0, 1, 1, 2, 2, 3, 3,
    ]


def test_errors_measured_against_the_precise_final_notice():
    tips = [
        # Final notice last in time even if listed first.
        _tip(1, "2026-01-02 12:00:00", "2026-01-02 12:30:00", 1),
        _tip(1, "2026-01-01 12:00:00", "2026-01-02 12:00:00", 60),  # 24 h lead, 30 min late
        _tip(1, "2026-01-02 08:00:00", "2026-01-02 13:00:00", 120),  # 5 h lead, 30 min early
    ]
    errors = tip_errors(tips)
    assert [(e.lead_h, e.z) for e in errors] == [(24.0, 0.5), (5.0, -0.25)]


def test_objects_without_a_precise_truth_or_excluded_are_skipped():
    tips = [
        _tip(1, "2026-01-01 00:00:00", "2026-01-02 00:00:00", 600),
        _tip(1, "2026-01-01 12:00:00", "2026-01-02 01:00:00", 300),  # final, too vague
        _tip(2, "2026-01-01 00:00:00", "2026-01-02 00:00:00", 600),
        _tip(2, "2026-01-02 00:10:00", "2026-01-02 00:10:00", 1),
        _tip(3, "2026-01-02 00:10:00", "2026-01-02 00:10:00", 1),  # only one notice
    ]
    assert tip_errors(tips, exclude=frozenset({2})) == []
    assert [e.norad_id for e in tip_errors(tips)] == [2]


def _synthetic_table(rng):
    errors = []
    for i, lead in enumerate((3.0, 12.0, 48.0, 100.0)):
        for z in rng.normal(0.0, i + 1.0, 4000):
            errors.append(TipError(norad_id=int(rng.integers(1000)), lead_h=lead, z=float(z)))
    return quantile_table(errors)


def test_sampling_reproduces_each_bucket():
    rng = np.random.default_rng(0)
    model = TipErrorModel(_synthetic_table(rng))
    for i, lead in enumerate((3.0, 12.0, 48.0, 100.0)):
        z = model.sample_z(lead, 50_000, np.random.default_rng(1))
        assert np.std(z) == pytest.approx(i + 1.0, rel=0.05)
        lo, hi = model.interval(lead, 0.99)
        assert np.mean((z >= lo) & (z <= hi)) == pytest.approx(0.99, abs=0.003)


def test_quantile_table_needs_every_bucket():
    with pytest.raises(ValueError, match="1-3d"):
        quantile_table([TipError(1, 3.0, 0.0), TipError(1, 12.0, 0.0), TipError(1, 100.0, 0.0)])


def test_shipped_table_is_well_formed():
    model = TipErrorModel.load(TABLE_PATH)
    assert len(model.quantiles) == len(LEAD_LABELS)
    for q in model.quantiles:
        assert q.size == model.probs.size
        assert np.all(np.diff(q) >= 0)  # quantiles never go backwards
        assert q[0] < 0 < q[-1]

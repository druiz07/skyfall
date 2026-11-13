from datetime import datetime, timedelta, timezone

from skyfall.sources.demo import DEMO_ELEMENTS_AGE, demo_reentries

REF = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


def test_demo_returns_three_synthetic_reentries():
    notices = demo_reentries(REF)

    assert [n.window_minutes for n in notices] == [43.0, 300.0, 900.0]
    assert all(n.source == "demo" for n in notices)
    assert len({n.norad_id for n in notices}) == 3


def test_demo_epochs_are_relative_to_reference_and_in_the_future():
    for notice in demo_reentries(REF):
        assert REF < notice.decay_epoch < REF + timedelta(days=3)
        assert notice.elements.epoch < notice.decay_epoch


def test_demo_works_without_reference_or_credentials(monkeypatch):
    monkeypatch.delenv("SPACETRACK_USER", raising=False)
    monkeypatch.delenv("SPACETRACK_PASSWORD", raising=False)

    notices = demo_reentries()

    assert len(notices) == 3
    assert notices[0].decay_epoch.tzinfo is not None


def test_demo_elements_are_a_little_older_than_the_notice():
    # Like a real notice: fresh elements, so a 3 h notice gets a narrow strip.
    for notice in demo_reentries(REF):
        assert notice.elements.epoch == notice.issued_at - DEMO_ELEMENTS_AGE

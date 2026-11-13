import pytest
from fastapi.testclient import TestClient

from skyfall.api import app

client = TestClient(app)


def test_list_reentries_returns_demo_notices():
    body = client.get("/reentries").json()

    assert [r["norad_id"] for r in body] == [900001, 900002, 900003]
    assert all(r["source"] == "demo" for r in body)


def test_corridor_lists_only_cells_of_the_99_zone():
    body = client.get("/reentries/900001/corridor").json()

    r90, r95, r99 = (body["regions"][k] for k in ("90", "95", "99"))
    assert 0 < r90["area_km2"] <= r95["area_km2"] <= r99["area_km2"]
    assert {c["region"] for c in body["cells"]} == {90, 95, 99}
    assert len(body["cells"]) == body["regions"]["99"]["n_cells"]
    # Only the 99 % zone is listed, so nearly all (not all) probability is there.
    assert 0.97 < sum(c["p"] for c in body["cells"]) <= 1.0 + 1e-6
    assert body["n_failed"] == 0
    assert len(body["breakup_points"]) > 0


def test_corridor_carries_the_easa_strips_of_the_comparison():
    body = client.get("/reentries/900001/corridor").json()
    cmp = {c["name"]: c for c in client.get("/reentries/900001/comparison").json()["closures"]}

    e70, e120 = body["easa"]
    assert (e70["half_width_km"], e120["half_width_km"]) == (70, 120)
    assert len(e70["cells"]) < len(e120["cells"])
    for e in (e70, e120):
        assert e["area_km2"] == pytest.approx(cmp[f"easa_{e['half_width_km']:.0f}km"]["area_km2"])
        assert 0 < e["coverage"] < 1


def test_wider_window_gives_bigger_corridor():
    narrow = client.get("/reentries/900001/corridor").json()  # +-43 min
    wide = client.get("/reentries/900003/corridor").json()  # +-15 h

    assert wide["regions"]["99"]["area_km2"] > narrow["regions"]["99"]["area_km2"]


def test_unknown_norad_returns_404():
    assert client.get("/reentries/12345/corridor").status_code == 404

# SKYFALL

**Where will falling space debris come down, and how much sky should be closed while we wait?**

SKYFALL turns official re-entry warnings for dead satellites and rocket stages into probability maps on a 3D globe, and compares them with the airspace closures used today.

> Successive warnings reduce the uncertainty. SKYFALL makes it visible, and lets you choose how much to close.

Built in a few days with [Claude Code](https://claude.com/claude-code). Open source, MIT licence.

---

## 1. The problem

Objects in low orbit circle the Earth about every 90 minutes. A re-entry warning gives a predicted time **plus or minus a window**, and that window is often hours long:

```
  warning: "re-entry at 15:16 UTC, ± 43 min"

  ±43 min   ≈ 1 lap of the planet
  ±5 h      ≈ 7 laps
  ±15 h     ≈ 20 laps

        .-~~~-.          every lap passes over a different
      /  ~~~~   \        strip of the Earth, so a long window
     |  ~~~~~~~  |  ←    means the object could fall almost
      \  ~~~~   /        anywhere under its path
        '-~~~-'
```

Because the time is so uncertain, authorities close long strips of airspace under the predicted path. With more and more re-entries (old satellites, rocket stages, end-of-life mega-constellation satellites), this matters more every year. A University of British Columbia study puts the chance of an uncontrolled re-entry over busy airspace at **~26 % per year** (Wright, Boley & Byers, see [References](#12-references)).

## 2. What SKYFALL does

```
  re-entry warning        thousands of          zones on the globe       compare with
  (time ± window,   ──▶   simulated falls  ──▶  90 % / 95 % / 99 %  ──▶  today's closure
   last orbit)            (time + debris)       of the falls             (EASA strip)
```

1. **Reads re-entry warnings** (TIP messages from Space-Track.org) and the orbit of each object.
2. **Simulates the fall many times.** Each run picks a re-entry time (based on how wrong past warnings really were), follows the orbit to that moment, and scatters debris along the path.
3. **Draws zones** that hold 90 %, 95 % and 99 % of the simulated falls, on a 0.5° grid.
4. **Compares them** with the strip used by the European aviation agency (EASA): the predicted path during the window, 70 or 120 km on each side.
5. **Plays the warning history:** each new warning narrows the zone, and the globe shows it shrinking until the real impact point appears.

## 3. Results

### 3.1 The zone shrinks with each warning (real case: NORAD 46698, a Starlink satellite)

Seven warnings, from 4 days before re-entry to the last one. The figures are for the **99 % zone**:

```
  warning window   99 % zone (million km²)
  ± 23 h           ████████████████████████████████████▌ 376
  ± 12 h           ███████████████████████████████████   351
  ± 10 h           ███████████████████████████████▌      315
  ±  4 h           ███████████████████▌                  196
  ±  2 h           ███████████▏                          112
  ±  1 h           ████▊                                  48
  ± 43 min         ███▌                                   35    → −91 % vs the first warning
```

It is the **warnings** that reduce the uncertainty. SKYFALL just shows how much is left. The confirmed impact point (-16.5°, -156.9°, central Pacific) falls inside the zone of the last warning.

A surprise along the way: the "estimated impact point" in the final warning was about **5 000 km** from where the satellite actually came down. Even a ±43 min window covers almost a full lap of the planet, so a single point is not a prediction you can close airspace around.

### 3.2 Exam with real re-entries the model had never seen

The model learned from objects with **even** catalogue numbers and was then tested on objects with **odd** numbers. Test set: **100 warnings issued less than 6 hours before re-entry** (63 objects), each checked against the confirmed impact point.

```
                       hits / 100    median area closed
  SKYFALL 90 %             89          15.6 M km²
  EASA 70 km strip         84          15.2 M km²     ← same sky, SKYFALL +5
  SKYFALL 95 %             95          24.5 M km²
  EASA 120 km strip        87          25.6 M km²     ← same sky, SKYFALL +8
  SKYFALL 99 %             96          72   M km²     ← honest: aims at 99, gets 96
```

For about the same amount of closed sky, the SKYFALL zones caught more real impacts than the EASA strips. With 100 warnings the noise is about ±3–4 points, so the +8 is clear and the +5 is likely.

For warnings issued **6–24 h** before re-entry (136 warnings), SKYFALL catches more impacts (89 / 93.4 / 96.3) but also closes much more sky than EASA (82 / 116 / 214 vs 49 / 80 M km²). There is no clear winner there.

### 3.3 The last warning of 46698 (±43 min)

```
  ■ SKYFALL 95 %       9.3 M km²   catches 95 %*
  ┄ EASA 120 km       10.0 M km²   catches 90 %*
  ■ SKYFALL 99 %      35.3 M km²   catches 99 %*   ← the price of asking for more

  * measured on the model's own simulated falls (an independent run); the real-world
    check is the exam in 3.2
```

Why does the EASA strip miss some? It only covers the path **during** the warning window. Real objects sometimes fall later than the window says (late much more often than early). Those falls land on the next lap, which the strip never touches.

## 4. Try it (demo mode, no account needed)

Requirements: Python 3.12+, Node.js 22+.

```powershell
# backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e "backend[dev]"
cd backend
$env:SKYFALL_SOURCE = "demo"
..\.venv\Scripts\python.exe -m uvicorn skyfall.api:app --port 8000

# frontend (another terminal)
cd frontend
npm install
npm run dev          # → http://localhost:5173
```

(On macOS/Linux use `.venv/bin/python` and `export SKYFALL_SOURCE=demo`.)

Demo mode uses **synthetic** objects and warnings generated by code (NORAD 900001–900003). When the API starts it calculates the demo zones in the background. The short warnings are ready in seconds; the ±15 h one takes a few minutes the first time.

In the web app (interface currently in Spanish): pick an object, then go through the four steps **path → 90 % → 95 % → 99 %**, press **▶** to play the warning history, and use **"┄ Comparar con EASA"** to draw the EASA strip. **"🛰 Mapa nítido"** switches on a sharper map (NASA Blue Marble).

### Real data (optional)

1. Create a free account at [space-track.org](https://www.space-track.org/auth/createAccount).
2. Copy `.env.example` to `.env` and fill in `SPACETRACK_USER` / `SPACETRACK_PASSWORD`.
3. Start the API with `SKYFALL_SOURCE=spacetrack` (or `auto`).

Responses are cached in `data_local/` (git-ignored) and requests are rate-limited to respect Space-Track's limits. To prepare a full history before a demo:

```powershell
cd backend
..\.venv\Scripts\python.exe scripts\precompute_history.py 46698
```

## 5. How it works

### 5.1 When does it fall? Learned from past warnings

We downloaded one year of warnings (Oct 2025 – Oct 2026, about 4 450 warnings for 680 objects). For each one we measured how far off its time was, in units of its own window:

```
  error = (real time − predicted time) / window

        early                 on time                 late
   ─────────────────────────────┼─────────────────────────────────▶
           ▁▂▃▅▇█████▇▅▃▂▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁                         long tail:
                     ↑                                          objects fall late
               most warnings are close,                         much more often
               but only ~85 % fall inside the window            than early
```

**The official window holds about 85 % of real re-entries, not 99 %.** So SKYFALL does not pick times evenly inside the window. It picks them from this measured error, in four groups by how early the warning was issued (<6 h, 6–24 h, 1–3 days, >3 days).

### 5.2 The orbit drifts sideways too

The orbit data in a warning is a few hours or days old. When we follow it to the real re-entry time, the path misses the real impact point sideways, by more the older the data is. We measured this on past re-entries: typically ~12 km for data under 6 h old, up to ~180 km for data several days old. That spread is added to the debris width.

### 5.3 Debris spreads along the path

```
          ← ~25 km sideways (plus orbit drift) →
   ───────●══════════════════════════════════▶   direction of flight
       break-up         debris lands 800 ± 400 km further along
```

These spread values are **assumptions**, not measured. They can be changed in `backend/skyfall/config.py`.

### 5.4 From simulated falls to zones

The globe is split into cells of 0.5° (about 55 km). Cells are filled in from most to least likely until the zone holds 90, 95 or 99 % of the falls.

To avoid **marking its own exam**, SKYFALL uses three separate simulations:

```
  run A  → decides which cells come first     (no randomness, smooth)
  run B  → decides where to stop (90/95/99 %)  (random falls)
  run C  → grades every closure, SKYFALL and EASA alike  (fresh random falls)
```

The EASA strip is drawn on the same grid: the orbit's path during the window (plus a few minutes either side, as the EASA bulletin says), 70 or 120 km on each side.

## 6. How we checked it

- **Learn / exam split.** Even catalogue numbers are used to learn the time error and orbit drift. Odd numbers are only used for the exam. NORAD 46698 is in neither group.
- **The exam** (section 3.2) uses the confirmed impact point of each object, published by Space-Track after re-entry.
- **The 46698 replay.** Using only what was known at each moment (orbit data published *before* each warning), all 7 warnings contain the real impact point. Of those 7 warnings, only 3 official windows contain the real re-entry time.

A detail that mattered: orbit data is often **published hours after** the moment it describes. Choosing it by its timestamp alone would have used "future" data in 4 of the 7 warnings for 46698. SKYFALL only uses data that was already published when the warning was issued.

## 7. Limitations (honest list)

- **Long warnings are not useful for closures.** With warnings issued days ahead, the 99 % zone covers most of the Earth (around 400 of 510 M km²). The value is in warnings issued hours ahead.
- **Warnings issued days ahead were not fully examined.** The exam covers warnings issued less than 24 h before re-entry. We stopped the longer ones because of compute time.
- **The 99 % zone catches ~96 % in reality.** The late tail is learned from only one year of data.
- **Debris spread is an assumption** (800 ± 400 km along the path, ±25 km sideways). The real spread depends on the object and is not public.
- **"Catches X %" in the app is measured on simulated falls.** Only section 3.2 uses real ones.
- **EASA updates its closures as new warnings arrive.** We compare warning by warning, which is fair, but not a full picture of a real operation.
- **No flights yet.** Counting affected flights (OpenSky) is planned but not done.
- **0.5° grid.** Narrow strips get slightly wider when drawn on cells. Both SKYFALL and EASA use the same grid, so the comparison stays fair.

## 8. Data and licences

- **No Space-Track data is in this repository.** Space-Track's user agreement does not allow redistribution. Everything downloaded stays in `data_local/` on your machine (git-ignored).
- The repo includes two small **statistical summaries** derived from past warnings: `backend/skyfall/data/tip_error_quantiles.json` (how wrong warning times were, as percentiles) and `track_drift.json` (sideways drift per data age). They contain no individual warnings, orbits or objects.
- The demo objects and warnings are **synthetic**.
- Map imagery: Natural Earth II (bundled with CesiumJS) and, optionally, NASA GIBS / Blue Marble.
- Credentials go in `.env`, which is git-ignored. Never commit it.

## 9. Project structure, API and tests

```
backend/
  skyfall/
    api.py            FastAPI app
    orbit.py          SGP4 propagation → latitude/longitude
    montecarlo.py     re-entry time sampling
    tip_errors.py     learned time error (5.1)
    track_drift.py    learned sideways drift (5.2)
    dispersion.py     debris spread (5.3)
    density.py        grid and zones
    corridor.py       full pipeline → 90/95/99 % zones
    closure.py        EASA strip
    comparison.py     SKYFALL vs EASA
    validation.py     replay against confirmed impacts
    sources/          demo (synthetic) and Space-Track client with cache
  scripts/            build tables, exam, precompute history
  tests/
frontend/             Vite + React + TypeScript + CesiumJS
```

| Endpoint | What it returns |
|---|---|
| `GET /health` | status and data source |
| `GET /reentries` | objects with an active warning (and recently fallen ones) |
| `GET /reentries/{norad}/track` | path during the window + predicted point |
| `GET /reentries/{norad}/corridor` | 90/95/99 % zones (+ EASA strips) |
| `GET /reentries/{norad}/comparison` | areas and catch rates, SKYFALL vs EASA |
| `GET /reentries/{norad}/history` | all warnings for an object + confirmed impact |
| `GET /reentries/{norad}/history/{i}/corridor` · `/track` | the same, for warning *i* |

Tests (never touch the network; fixed random seeds):

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest
```

## 10. Next steps

- **Affected flights:** cross the zones with live air traffic from OpenSky (flights, flight-hours).
- **When to close each piece of sky:** a strip does not need to be closed for the whole window, only while the object can be overhead.
- Examine longer warnings and more years of data, especially for the late tail.

## 11. Acknowledgements

Orbit propagation with [`sgp4`](https://pypi.org/project/sgp4/), globe with [CesiumJS](https://cesium.com/platform/cesiumjs/), warnings from [Space-Track.org](https://www.space-track.org) (18th/19th Space Defense Squadron).

## 12. References

- E. Wright, A. Boley, M. Byers. *Airspace closures due to reentering space objects.* Scientific Reports (2025). University of British Columbia.
- C. Pardini, L. Anselmo. Re-entry risk on the ground and for aviation. *Acta Astronautica* (2026).
- EASA Safety Information Bulletins 2022-07 and 2022-09 (Long March 5B re-entries, 2022): basis of the 70 / 120 km strips.
- Space-Track on the TIP window being "± WINDOW minutes": [x.com/SpaceTrackOrg/status/1391128834674544642](https://x.com/SpaceTrackOrg/status/1391128834674544642).

## Licence

[MIT](LICENSE) © Daniel Ruiz Figueroa

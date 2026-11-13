import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  getHealth,
  getHistory,
  getNoticeCorridor,
  getNoticeTrack,
  getReentries,
  easaPair,
  type Corridor,
  type Health,
  type History,
  type Level,
  type ReentrySummary,
  type Track,
} from "./api";
import Globe from "./Globe";

const panel: CSSProperties = {
  position: "absolute",
  top: 12,
  left: 12,
  width: 260,
  maxHeight: "calc(100% - 24px)",
  boxSizing: "border-box", // padding inside maxHeight, or the bottom is cut off
  overflowY: "auto",
  padding: 12,
  font: "13px system-ui",
  color: "#eee",
  background: "rgba(10,12,20,0.8)",
  borderRadius: 6,
};

function windowLabel(minutes: number): string {
  return minutes < 90 ? `±${Math.round(minutes)} min` : `±${Math.round(minutes / 60)} h`;
}

function utc(iso: string): string {
  return iso.slice(0, 16).replace("T", " ") + " UTC";
}

// Replay speed: ~25 s for the 7 notices of 46698, short enough for a social-media video.
const PLAY_STEP_MS = 3500;
// On the last notice the camera glides to its red point and rests there before "it came down".
const LAST_STEP_MS = 4000;
// Camera during the replay: the same slow glide to each red point and to where it really fell;
// the rest of each PLAY_STEP_MS it stays still.
const FOLLOW_FLIGHT_S = 2.5;
const LANDED_FLIGHT_S = 2.5;

// The globe is explained one layer at a time: each step adds one thing.
const STEPS: { title: string; level: Level | null }[] = [
  { title: "Ruta", level: null },
  { title: "90 %", level: 90 },
  { title: "95 %", level: 95 },
  { title: "99 %", level: 99 },
];

function millionKm2(corridor: Corridor, level: Level): string {
  const m = corridor.regions[String(level) as "90" | "95" | "99"].area_km2 / 1e6;
  return `${m.toLocaleString("es-ES", { maximumFractionDigits: 1 })} millones de km²`;
}

function stepButton(active: boolean): CSSProperties {
  return {
    flex: 1,
    padding: "4px 6px",
    font: "inherit",
    color: "inherit",
    cursor: "pointer",
    border: "1px solid rgba(255,255,255,0.25)",
    borderRadius: 4,
    background: active ? "rgba(255,200,0,0.3)" : "transparent",
  };
}

function StepText({
  step,
  track,
  corridor,
}: {
  step: number;
  track: Track;
  corridor: Corridor | null;
}) {
  if (step === 1)
    return (
      <div style={{ lineHeight: 1.45 }}>
        <p style={{ margin: "0 0 6px" }}>
          <span style={{ color: "gold" }}>━</span> Por aquí pasa el satélite durante la ventana del
          aviso. Da una vuelta a la Tierra cada hora y media, así que la línea puede rodear casi
          todo el planeta y verse cruzada.
        </p>
        <p style={{ margin: 0 }}>
          <span style={{ color: "red" }}>●</span>{" "}
          {track.impact.source === "tip"
            ? "Punto que da el aviso"
            : "Dónde estaría a la hora del aviso"}
          : es el centro de la ventana, <b>no</b> el sitio donde va a caer.
        </p>
      </div>
    );
  if (step === 2)
    return (
      <div style={{ lineHeight: 1.45 }}>
        <p style={{ margin: "0 0 6px" }}>
          Lo rojo es más ancho que la línea porque al romperse los trozos se abren a los lados, y
          porque la órbita que da el aviso puede estar algo desviada. Llega un poco más allá del
          final de la línea porque los trozos siguen volando hacia delante después de romperse.
        </p>
        <p style={{ margin: 0 }}>
          Cielo que habría que cerrar: <b>{corridor ? millionKm2(corridor, 90) : "calculando…"}</b>
        </p>
      </div>
    );
  if (step === 3)
    return (
      <div style={{ lineHeight: 1.45 }}>
        <p style={{ margin: "0 0 6px" }}>
          Lo naranja sale porque a veces el objeto cae <b>tarde</b>, fuera de la ventana del aviso.
          Entonces da una vuelta más y cae en otra franja, más al oeste, porque la Tierra ha girado
          por debajo. Por eso aparecen trozos naranjas lejos de la línea dorada. También se ensancha
          un poco lo rojo.
        </p>
        <p style={{ margin: 0 }}>
          Cielo que habría que cerrar: <b>{corridor ? millionKm2(corridor, 95) : "calculando…"}</b>
          {corridor && <> (antes {millionKm2(corridor, 90)})</>}
        </p>
      </div>
    );
  if (step === 4)
    return (
      <div style={{ lineHeight: 1.45 }}>
        <p style={{ margin: "0 0 6px" }}>
          Lo amarillo son los retrasos raros: el objeto cae dos, tres o más vueltas tarde. Cada
          vuelta es una franja nueva en otra parte del mundo, y aunque cada una es poco probable,
          hay que cerrarlas todas.
        </p>
        <p style={{ margin: "0 0 6px" }}>
          Cielo que habría que cerrar: <b>{corridor ? millionKm2(corridor, 99) : "calculando…"}</b>
          {corridor && <> (antes {millionKm2(corridor, 95)})</>}
        </p>
        <p style={{ margin: 0, opacity: 0.7 }}>
          Ojo: probado con caídas reales de avisos de menos de 6 h, esta zona atrapó 96 de cada 100,
          no 99. Los retrasos muy largos son tan raros que cuesta aprenderlos.
        </p>
      </div>
    );
  return null;
}

function NoticeBar({
  history,
  index,
  onPick,
  play,
}: {
  history: History;
  index: number;
  onPick: (i: number) => void;
  play: { playing: boolean; preparing: boolean; toggle: () => void };
}) {
  const n = history.notices[index];
  return (
    <section style={{ marginTop: 10 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
        <div style={{ flex: 1, opacity: 0.8 }}>
          {history.name} · {history.notices.length}{" "}
          {history.notices.length === 1 ? "aviso" : "avisos"}
        </div>
        {history.notices.length > 1 && (
          <button onClick={play.toggle} disabled={play.preparing} style={stepButton(play.playing)}>
            {play.preparing ? "preparando…" : play.playing ? "⏸" : "▶"}
          </button>
        )}
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginBottom: 6 }}>
        {history.notices.map((h) => (
          <button
            key={h.index}
            onClick={() => onPick(h.index)}
            style={stepButton(h.index === index)}
          >
            {windowLabel(h.window_minutes)}
          </button>
        ))}
      </div>
      {n && (
        <div style={{ opacity: 0.7, lineHeight: 1.45 }}>
          {n.issued_at && <div>aviso emitido {utc(n.issued_at)}</div>}
          <div>
            caída prevista {utc(n.decay_epoch)} {windowLabel(n.window_minutes)}
          </div>
        </div>
      )}
    </section>
  );
}

// Same colours as the zone painted on the globe (zone.ts); each step adds one ring.
const ZONE_LEGEND: { level: Level; color: string; text: string }[] = [
  { level: 90, color: "#e6281e", text: "los trozos caen aquí 9 de cada 10 veces" },
  { level: 95, color: "#ff7800", text: "con lo naranja, 19 de cada 20" },
  { level: 99, color: "#fff08c", text: "con lo amarillo, 99 de cada 100" },
];

// Big enough to read in a phone-sized video.
function Counter({
  level,
  corridor,
  first,
  window,
  easa,
}: {
  level: Level;
  corridor: Corridor;
  first: Corridor | undefined;
  window: number;
  easa: boolean;
}) {
  const key = String(level) as "90" | "95" | "99";
  const area = corridor.regions[key].area_km2;
  const strip = easa ? easaPair(corridor, level) : undefined;
  const zoneColor = ZONE_LEGEND.find((z) => z.level === level)!.color;
  const change = first && first !== corridor ? area / first.regions[key].area_km2 - 1 : null;
  return (
    <div
      style={{
        position: "absolute",
        top: 12,
        right: 12,
        padding: "12px 16px",
        textAlign: "right",
        font: "15px system-ui",
        color: "#eee",
        background: "rgba(10,12,20,0.8)",
        borderRadius: 6,
      }}
    >
      <div style={{ opacity: 0.7 }}>
        aviso {windowLabel(window)} · zona {level} %
      </div>
      {strip ? (
        <div style={{ margin: "6px 0", fontSize: 19, lineHeight: 1.5 }}>
          <CompareLine
            mark={<span style={{ color: zoneColor }}>■</span>}
            name={`SKYFALL ${level} %`}
            km2={area}
            share={level}
          />
          <CompareLine
            mark={<span style={{ color: "#50c8ff" }}>┄</span>}
            name={`EASA ${strip.half_width_km} km`}
            km2={strip.area_km2}
            share={Math.round(strip.coverage * 100)}
          />
          <div style={{ fontSize: 12, opacity: 0.7 }}>
            * de cada 100 caídas simuladas por el modelo
          </div>
        </div>
      ) : (
        <div style={{ fontSize: 30, fontWeight: 600 }}>{millionKm2(corridor, level)}</div>
      )}
      {change !== null && (
        <div style={{ fontSize: 22, color: change < 0 ? "#7CFC9A" : "#ff8080" }}>
          {change > 0 ? "+" : "−"}
          {Math.abs(Math.round(change * 100))} % respecto al primer aviso
        </div>
      )}
      {/* Whoever watches the video should not need to remember step 1. */}
      <div
        style={{
          marginTop: 8,
          paddingTop: 8,
          borderTop: "1px solid rgba(255,255,255,0.2)",
          textAlign: "left",
          fontSize: 13,
          lineHeight: 1.4,
          maxWidth: 260,
          marginLeft: "auto",
        }}
      >
        <div>
          <span style={{ color: "gold" }}>━</span> ruta del satélite durante la ventana del aviso
          (da una vuelta cada hora y media)
        </div>
        <div>
          <span style={{ color: "red" }}>●</span> centro de la ventana del aviso, no dónde cae
        </div>
        {ZONE_LEGEND.filter((z) => z.level <= level).map((z) => (
          <div key={z.level}>
            <span style={{ color: z.color }}>■</span> {z.text}
          </div>
        ))}
        {strip && (
          <div>
            <span style={{ color: "#50c8ff" }}>┄</span> cinta EASA: solo cierra la vuelta del aviso,
            no las vueltas tarde
          </div>
        )}
      </div>
    </div>
  );
}

function CompareLine({
  mark,
  name,
  km2,
  share,
}: {
  mark: ReactNode;
  name: string;
  km2: number;
  share: number;
}) {
  const m = (km2 / 1e6).toLocaleString("es-ES", { maximumFractionDigits: 1 });
  return (
    <div style={{ display: "flex", gap: 12, justifyContent: "space-between" }}>
      <span style={{ textAlign: "left" }}>
        {mark} {name}
      </span>
      <span>
        <b>{m} M km²</b> · atrapa {share}*
      </span>
    </div>
  );
}

// Exam v2: 100 notices issued < 6 h before the fall, objects the model never learnt from.
// Each SKYFALL zone beside the EASA strip that closes a similar amount of sky.
const REAL_EXAM: Record<Level, { skyfall: number; easaKm: number; easa: number }> = {
  90: { skyfall: 89, easaKm: 70, easa: 84 },
  95: { skyfall: 95, easaKm: 120, easa: 87 },
  99: { skyfall: 95, easaKm: 120, easa: 87 },
};

function RealExam({ level }: { level: Level }) {
  // The 99 % zone shares its strip with the 95 % one; the fair pair is the 95 % zone.
  const zone = level === 99 ? 95 : level;
  const r = REAL_EXAM[level];
  return (
    <div
      style={{
        marginTop: 8,
        padding: "8px 10px",
        border: "1px solid rgba(80,200,255,0.4)",
        borderRadius: 4,
        lineHeight: 1.45,
      }}
    >
      <div style={{ fontWeight: 600, marginBottom: 4 }}>Examen con caídas reales</div>
      <div style={{ opacity: 0.8, marginBottom: 6 }}>
        100 avisos de menos de 6 h, de objetos que el modelo nunca vio. Cerrando casi el mismo
        cielo, de cada 100 caídas atrapó:
      </div>
      <div>
        SKYFALL {zone} %: <b>{r.skyfall}</b> · EASA {r.easaKm} km: <b>{r.easa}</b>
      </div>
    </div>
  );
}

// Where "now" sits against a notice's window. Space-Track only confirms a fall afterwards,
// so an object can stay "coming down" for hours after its whole window has gone by.
type Timing = "ahead" | "inside" | "past";

function timing(r: ReentrySummary, now: number): Timing {
  const centre = Date.parse(r.decay_epoch);
  const half = r.window_minutes * 60_000;
  if (now > centre + half) return "past";
  return now >= centre - half ? "inside" : "ahead";
}

function ReentryList({
  title,
  items,
  selected,
  onPick,
  now,
}: {
  title: string;
  items: ReentrySummary[];
  selected: number | null;
  onPick: (norad: number) => void;
  now?: number; // given only for the live list, which tags each object by its window
}) {
  // Unconfirmed objects whose window is over go last: they have most likely fallen already.
  const shown =
    now === undefined
      ? items
      : [...items].sort(
          (a, b) => Number(timing(a, now) === "past") - Number(timing(b, now) === "past"),
        );
  return (
    <>
      <div style={{ opacity: 0.8, margin: "12px 0 4px" }}>{title}</div>
      <div style={{ maxHeight: 220, overflowY: "auto", paddingRight: 4 }}>
        {shown.map((r) => {
          const t = now === undefined ? "ahead" : timing(r, now);
          return (
            <button
              key={r.norad_id}
              onClick={() => onPick(r.norad_id)}
              style={{
                display: "block",
                width: "100%",
                textAlign: "left",
                marginBottom: 6,
                padding: "6px 8px",
                font: "inherit",
                color: "inherit",
                cursor: "pointer",
                border: "1px solid rgba(255,255,255,0.15)",
                borderRadius: 4,
                background: r.norad_id === selected ? "rgba(255,200,0,0.25)" : "transparent",
                opacity: t === "past" ? 0.55 : 1,
              }}
            >
              <div>{r.name}</div>
              {t === "inside" && (
                <div style={{ color: "gold" }}>⏳ cayendo ahora (dentro del margen)</div>
              )}
              {t === "past" && <div>❔ hora pasada, sin confirmar</div>}
              <div style={{ opacity: 0.7 }}>
                NORAD {r.norad_id} ·{" "}
                {r.landed ? (
                  <>
                    cayó {utc(r.decay_epoch)}
                    {r.predicted_lat !== null && r.predicted_lon !== null && (
                      <>
                        {" "}
                        · ({r.predicted_lat.toFixed(1)}, {r.predicted_lon.toFixed(1)})
                      </>
                    )}
                  </>
                ) : (
                  <>
                    {utc(r.decay_epoch)} · {windowLabel(r.window_minutes)}
                  </>
                )}
              </div>
            </button>
          );
        })}
      </div>
    </>
  );
}

const input: CSSProperties = {
  flex: 1,
  minWidth: 0,
  padding: "4px 6px",
  font: "inherit",
  color: "inherit",
  background: "rgba(255,255,255,0.08)",
  border: "1px solid rgba(255,255,255,0.25)",
  borderRadius: 4,
};

// The sharp-map choice is remembered per browser; storage can be blocked, so never rely on it.
const SHARP_KEY = "skyfall.sharpMap";

function readSharp(): boolean {
  try {
    return localStorage.getItem(SHARP_KEY) === "1";
  } catch {
    return false;
  }
}

function writeSharp(on: boolean): void {
  try {
    localStorage.setItem(SHARP_KEY, on ? "1" : "0");
  } catch {
    // not remembered: fine
  }
}

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [reentries, setReentries] = useState<ReentrySummary[]>([]);
  const [selected, setSelected] = useState<number | null>(null); // NORAD id
  const [history, setHistory] = useState<History | null>(null);
  const [noticeIndex, setNoticeIndex] = useState<number | null>(null);
  const [track, setTrack] = useState<Track | null>(null);
  const [corridor, setCorridor] = useState<Corridor | null>(null);
  const [loadingZone, setLoadingZone] = useState(false);
  const [step, setStep] = useState(1);
  const [easa, setEasa] = useState(false);
  const [sharp, setSharp] = useState(() => readSharp());
  const [noradInput, setNoradInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const [showLanded, setShowLanded] = useState(false);
  const [now, setNow] = useState(Date.now()); // ticks every minute so the list tags stay true
  // A notice never changes once issued: keep what was shown, so going back is instant.
  const tracks = useRef(new Map<string, Track>());
  const corridors = useRef(new Map<string, Corridor>());
  const selectedNow = useRef(selected);
  selectedNow.current = selected;

  async function loadTrack(norad: number, index: number): Promise<Track> {
    const key = `${norad}/${index}`;
    const t = tracks.current.get(key) ?? (await getNoticeTrack(norad, index));
    tracks.current.set(key, t);
    return t;
  }

  async function loadCorridor(norad: number, index: number): Promise<Corridor> {
    const key = `${norad}/${index}`;
    const c = corridors.current.get(key) ?? (await getNoticeCorridor(norad, index));
    corridors.current.set(key, c);
    return c;
  }

  useEffect(() => {
    Promise.all([getHealth(), getReentries()])
      .then(([h, r]) => {
        setHealth(h);
        setReentries([...r].sort((a, b) => a.decay_epoch.localeCompare(b.decay_epoch)));
      })
      .catch((e: Error) => setError(e.message));
    const id = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(id);
  }, []);

  // A new object: fetch its series and start on the newest notice, the most precise one.
  useEffect(() => {
    if (selected === null) return;
    let stale = false; // a slower answer for a previous click must not overwrite this one
    setHistory(null);
    setNoticeIndex(null);
    setTrack(null);
    setCorridor(null);
    setStep(1);
    setError(null);
    setPlaying(false);
    setShowLanded(false);
    getHistory(selected)
      .then((h) => {
        if (stale) return;
        setHistory(h);
        setNoticeIndex(h.notices.length - 1);
      })
      .catch((e: Error) => !stale && setError(e.message));
    return () => {
      stale = true;
    };
  }, [selected]);

  // Another notice of the same object: swap route and zone, keep the step the user is on.
  useEffect(() => {
    // Right after a click, noticeIndex still belongs to the previous object: wait for this
    // object's series, or a cached notice of it would pull the camera to the wrong place.
    if (selected === null || noticeIndex === null || history?.norad_id !== selected) return;
    let stale = false;
    const key = `${selected}/${noticeIndex}`;
    const t = tracks.current.get(key);
    if (t) setTrack(t);
    else
      loadTrack(selected, noticeIndex)
        .then((t) => !stale && setTrack(t))
        .catch((e: Error) => !stale && setError(e.message));
    const c = corridors.current.get(key);
    setCorridor(c ?? null);
    setLoadingZone(!c);
    // The zone takes seconds the first time (long windows, minutes), then comes from a cache.
    if (!c)
      loadCorridor(selected, noticeIndex)
        .then((c) => !stale && setCorridor(c))
        .catch((e: Error) => !stale && setError(e.message))
        .finally(() => !stale && setLoadingZone(false));
    return () => {
      stale = true;
    };
  }, [selected, noticeIndex, history]);

  // Replay: one notice every PLAY_STEP_MS, then "it came down here" on the last one.
  useEffect(() => {
    if (!playing || !history || noticeIndex === null) return;
    const id = setTimeout(
      () => {
        if (noticeIndex < history.notices.length - 1) setNoticeIndex(noticeIndex + 1);
        else {
          setPlaying(false);
          setShowLanded(true);
        }
      },
      noticeIndex === history.notices.length - 1 ? LAST_STEP_MS : PLAY_STEP_MS,
    );
    return () => clearTimeout(id);
  }, [playing, history, noticeIndex]);

  // Everything is fetched before the replay starts, so it never stalls halfway.
  async function togglePlay() {
    if (playing) return setPlaying(false);
    if (selected === null || !history) return;
    const norad = selected;
    setPreparing(true);
    setShowLanded(false);
    try {
      await Promise.all(
        history.notices.flatMap((n) => [loadTrack(norad, n.index), loadCorridor(norad, n.index)]),
      );
      if (norad !== selectedNow.current) return; // the user opened another object meanwhile
      setNoticeIndex(0);
      setPlaying(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPreparing(false);
    }
  }

  function pickNotice(i: number) {
    setPlaying(false);
    setNoticeIndex(i);
  }

  // The counter compares the zone on screen with the same zone of the first notice.
  const level = STEPS[step - 1].level;
  // Replay: the camera follows each notice's red point, then glides to where it really fell.
  const followed = playing && track ? track.impact : null;
  const focus = useMemo(
    () =>
      showLanded && history?.landed
        ? { lat: history.landed.lat, lon: history.landed.lon, seconds: LANDED_FLIGHT_S }
        : followed && { lat: followed.lat, lon: followed.lon, seconds: FOLLOW_FLIGHT_S },
    [showLanded, history, followed],
  );
  const first = selected === null ? undefined : corridors.current.get(`${selected}/0`);
  // Always shown for objects that fell; the replay keeps it back for its ending.
  const landed = useMemo(
    () =>
      (showLanded || !playing) && history?.landed
        ? {
            lat: history.landed.lat,
            lon: history.landed.lon,
            label: `cayó aquí · ${utc(history.landed.decay_epoch)}`,
          }
        : null,
    [showLanded, playing, history],
  );

  function openNorad(e: FormEvent) {
    e.preventDefault();
    const id = Number(noradInput.trim());
    if (Number.isInteger(id) && id > 0) setSelected(id);
  }

  return (
    <>
      <Globe
        track={track}
        corridor={corridor}
        level={level}
        easa={easa}
        landed={landed}
        focus={focus}
        sharp={sharp}
      />
      {history && corridor && level !== null && noticeIndex !== null && (
        <Counter
          level={level}
          corridor={corridor}
          first={first}
          window={history.notices[noticeIndex].window_minutes}
          easa={easa}
        />
      )}
      <aside style={panel}>
        <div style={{ fontWeight: 600, letterSpacing: 1 }}>SKYFALL</div>
        <div style={{ opacity: 0.6, marginBottom: 10 }}>
          {health ? `fuente: ${health.source}` : "…"} · {reentries.length} avisos
        </div>
        <button
          onClick={() => {
            setSharp(!sharp);
            writeSharp(!sharp);
          }}
          title="Foto de satélite Blue Marble de la NASA (necesita internet)"
          style={{ ...stepButton(sharp), width: "100%", marginBottom: 10 }}
        >
          🛰 Mapa nítido{sharp ? " (en línea)" : ""}
        </button>
        <form onSubmit={openNorad} style={{ marginBottom: 10 }}>
          <div style={{ opacity: 0.8, marginBottom: 4 }}>Ver historial de NORAD:</div>
          <div style={{ display: "flex", gap: 4 }}>
            <input
              value={noradInput}
              onChange={(e) => setNoradInput(e.target.value)}
              inputMode="numeric"
              placeholder="p. ej. 46698"
              style={input}
            />
            <button type="submit" style={{ ...stepButton(false), flex: "none" }}>
              Ver
            </button>
          </div>
        </form>
        {error && <div style={{ color: "#ff8080", marginBottom: 8 }}>API: {error}</div>}
        {/* What is being looked at goes first; the live list sits below in its own scroll box. */}
        {selected !== null && !history && !error && (
          <div style={{ marginBottom: 8, color: "gold" }}>buscando avisos de {selected}…</div>
        )}
        {history && noticeIndex !== null && (
          <NoticeBar
            history={history}
            index={noticeIndex}
            onPick={pickNotice}
            play={{ playing, preparing, toggle: togglePlay }}
          />
        )}
        {track && (
          <section style={{ marginTop: 10 }}>
            <div style={{ display: "flex", gap: 4, marginBottom: 8 }}>
              {STEPS.map((st, i) => (
                <button key={i} onClick={() => setStep(i + 1)} style={stepButton(step === i + 1)}>
                  {i + 1} {st.title}
                </button>
              ))}
            </div>
            <StepText step={step} track={track} corridor={corridor} />
            {step > 1 && (
              <button
                onClick={() => setEasa(!easa)}
                style={{ ...stepButton(easa), width: "100%", marginTop: 8 }}
              >
                <span style={{ color: "#50c8ff" }}>┄</span> Comparar con EASA
              </button>
            )}
            {step > 1 && easa && level !== null && <RealExam level={level} />}
          </section>
        )}
        {loadingZone && step > 1 && (
          <div style={{ marginTop: 8, color: "gold" }}>calculando la zona…</div>
        )}
        <ReentryList
          title="Por caer (en directo):"
          items={reentries.filter((r) => !r.landed)}
          selected={selected}
          onPick={setSelected}
          now={now}
        />
        {/* Confirmations: Space-Track only says "it is down" after the fall. */}
        {reentries.some((r) => r.landed) && (
          <ReentryList
            title="Ya caídos (último día):"
            items={reentries.filter((r) => r.landed)}
            selected={selected}
            onPick={setSelected}
          />
        )}
      </aside>
    </>
  );
}

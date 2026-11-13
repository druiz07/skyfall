// Shapes returned by the FastAPI backend (see backend/skyfall/models.py).

export interface Health {
  status: string;
  version: string;
  source: "demo" | "spacetrack";
}

export interface ReentrySummary {
  norad_id: number;
  name: string;
  decay_epoch: string;
  window_minutes: number;
  inclination_deg: number;
  source: "demo" | "spacetrack";
  issued_at: string | null;
  predicted_lat: number | null;
  predicted_lon: number | null;
  landed: boolean; // the newest notice confirms it already fell, at predicted_lat/lon
}

export interface Track {
  norad_id: number;
  start: string;
  end: string;
  step_seconds: number;
  points: [number, number][]; // [lat, lon]
  impact: { lat: number; lon: number; source: "tip" | "orbit" };
}

export type Level = 90 | 95 | 99;

export interface Corridor {
  norad_id: number;
  n_samples: number;
  resolution_deg: number;
  regions: Record<"90" | "95" | "99", { area_km2: number; n_cells: number }>;
  cells: { lat: number; lon: number; p: number; region: Level }[]; // only cells inside the 99 % zone
  easa: EasaClosure[]; // today's precautionary strips, 70 then 120 km
}

// coverage: share of the model's test fragments inside the strip (not real re-entries).
export interface EasaClosure {
  half_width_km: number;
  area_km2: number;
  coverage: number;
  cells: [number, number][]; // closed cell centres [lat, lon]
}

// Each SKYFALL zone is set beside the EASA strip that closes a similar amount of sky.
export function easaPair(corridor: Corridor, level: Level): EasaClosure | undefined {
  const width = level === 90 ? 70 : 120;
  return corridor.easa?.find((e) => e.half_width_km === width);
}

export interface HistoryNotice {
  index: number; // position in the series, oldest = 0
  issued_at: string | null;
  decay_epoch: string;
  window_minutes: number;
  predicted_lat: number | null;
  predicted_lon: number | null;
}

export interface History {
  norad_id: number;
  name: string;
  notices: HistoryNotice[]; // forecasts only, oldest first
  landed: { decay_epoch: string; lat: number; lon: number } | null;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`/api${path}`);
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export const getHealth = () => get<Health>("/health");
export const getReentries = () => get<ReentrySummary[]>("/reentries");
export const getHistory = (norad: number) => get<History>(`/reentries/${norad}/history`);
export const getNoticeTrack = (norad: number, index: number) =>
  get<Track>(`/reentries/${norad}/history/${index}/track`);
export const getNoticeCorridor = (norad: number, index: number) =>
  get<Corridor>(`/reentries/${norad}/history/${index}/corridor`);

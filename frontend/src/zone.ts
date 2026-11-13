import type { Corridor, EasaClosure, Level } from "./api";

// Onion colours: the 90 % core strongest, the 99 % fringe faintest. [r, g, b, alpha 0-255]
const LEVEL_RGBA: Record<Level, [number, number, number, number]> = {
  90: [230, 40, 30, 200],
  95: [255, 120, 0, 190],
  99: [255, 240, 140, 130],
};

/**
 * Paints the corridor as an equirectangular image, one pixel per grid cell
 * (0.5° → 720×360), north at the top, longitude -180 at the left edge.
 */
export function zoneImage(
  corridor: Corridor,
  chosen: Level,
  easa?: EasaClosure,
): HTMLCanvasElement {
  const res = corridor.resolution_deg;
  const width = Math.round(360 / res);
  const height = Math.round(180 / res);
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d")!;
  const img = ctx.createImageData(width, height);

  for (const cell of corridor.cells) {
    // Only the chosen zone and the ones inside it: each step adds one ring.
    if (cell.region > chosen) continue;
    const row = height - 1 - Math.floor((cell.lat + 90) / res);
    const col = ((Math.floor((cell.lon + 180) / res) % width) + width) % width;
    const [r, g, b, a] = LEVEL_RGBA[cell.region];
    const k = 4 * (row * width + col);
    img.data[k] = r;
    img.data[k + 1] = g;
    img.data[k + 2] = b;
    img.data[k + 3] = a;
  }
  if (easa) outline(img, easa, res);
  ctx.putImageData(img, 0, 0);
  return canvas;
}

// Only the edge of the EASA strip, so the SKYFALL zone underneath stays visible.
const EASA_RGBA = [80, 200, 255, 255];
const EDGE_CELLS = 2;

function outline(img: ImageData, easa: EasaClosure, res: number): void {
  const { width, height } = img;
  const closed = new Set<number>();
  for (const [lat, lon] of easa.cells) {
    const row = height - 1 - Math.floor((lat + 90) / res);
    const col = ((Math.floor((lon + 180) / res) % width) + width) % width;
    closed.add(row * width + col);
  }
  // Edge = within EDGE_CELLS of an open cell, so the line is that many cells thick.
  const isOpen = (row: number, col: number) =>
    row >= 0 && row < height && !closed.has(row * width + ((col + width) % width)); // lon wraps
  for (const k of closed) {
    const row = Math.floor(k / width);
    const col = k % width;
    let edge = false;
    for (let d = 1; d <= EDGE_CELLS && !edge; d++)
      edge =
        isOpen(row, col - d) ||
        isOpen(row, col + d) ||
        isOpen(row - d, col) ||
        isOpen(row + d, col);
    if (edge) img.data.set(EASA_RGBA, 4 * k);
  }
}

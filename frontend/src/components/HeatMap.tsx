import { useEffect, useMemo, useRef, useState } from "react";
import type { Report } from "../api";
import { euro, percent, signedPercent } from "../format";
import { usePreference } from "../preferences";

type Tile = {
  isin: string;
  name: string;
  size: number;
  value: number | null;
  cost: number;
  changes: Record<Mode, number | null>;
};
type Rect = { x: number; y: number; w: number; h: number };
type Mode = "seance" | "mois" | "achat";

/** Per measure: its name, and where the three steps of each side begin. */
const MODES: Record<Mode, { label: string; steps: [number, number, number] }> = {
  seance: { label: "Séance", steps: [0.0025, 0.01, 0.025] },
  mois: { label: "30 jours", steps: [0.01, 0.05, 0.12] },
  achat: { label: "Depuis l'achat", steps: [0.02, 0.1, 0.25] },
};
const GAP = 2; // surface showing between two tiles

/** -3 to 3: which step of the scale a change falls in. Unknown is drawn as flat. */
const stepOf = (change: number | null, steps: [number, number, number]) => {
  if (change == null) return 0;
  const size = Math.abs(change);
  const step = size < steps[0] ? 0 : size < steps[1] ? 1 : size < steps[2] ? 2 : 3;
  return change < 0 ? -step : step;
};
const fill = (step: number) =>
  step === 0 ? "var(--heat-flat)" : `var(--heat-${step < 0 ? "down" : "up"}-${Math.abs(step)})`;
// The strongest steps are dark on a light page and bright on a dark one: their label flips.
const ink = (step: number) => (Math.abs(step) === 3 ? "var(--surface)" : "var(--ink)");

/** Squarified layout: tiles as close to squares as the sizes allow, largest first. */
function layout(sizes: number[], box: Rect): Rect[] {
  const total = sizes.reduce((sum, size) => sum + size, 0);
  const rects: Rect[] = new Array(sizes.length);
  if (total <= 0 || box.w <= 0 || box.h <= 0) return rects.fill({ x: 0, y: 0, w: 0, h: 0 });
  const scale = (box.w * box.h) / total;
  const areas = sizes.map((size) => size * scale);
  let { x, y, w, h } = box;
  let start = 0;
  const worst = (row: number[], side: number) => {
    const sum = row.reduce((a, b) => a + b, 0);
    const thickness = sum / side;
    return Math.max(...row.map((area) => Math.max(thickness ** 2 / area, area / thickness ** 2)));
  };
  while (start < areas.length) {
    const side = Math.min(w, h);
    let end = start + 1;
    while (
      end < areas.length &&
      worst(areas.slice(start, end + 1), side) <= worst(areas.slice(start, end), side)
    ) {
      end += 1;
    }
    const row = areas.slice(start, end);
    const thickness = row.reduce((a, b) => a + b, 0) / side;
    let offset = 0;
    row.forEach((area, i) => {
      const length = area / thickness;
      rects[start + i] =
        w >= h
          ? { x, y: y + offset, w: thickness, h: length }
          : { x: x + offset, y, w: length, h: thickness };
      offset += length;
    });
    if (w >= h) {
      x += thickness;
      w -= thickness;
    } else {
      y += thickness;
      h -= thickness;
    }
    start = end;
  }
  return rects;
}

/** The longest run of whole words of `name` that fits in `width` pixels, or nothing. */
const fitting = (name: string, width: number) => {
  const room = Math.floor(width / 7.2);
  const words = name.split(" ");
  let text = "";
  for (const word of words) {
    const next = text ? `${text} ${word}` : word;
    if (next.length > room) break;
    text = next;
  }
  return text;
};

/**
 * The portfolio at a glance: one tile per instrument, as large as its weight,
 * coloured by its change. Every figure is also in the tables below.
 */
export function HeatMap({ report }: { report: Report }) {
  const [stored, setMode] = usePreference<string>("carte.mesure", "seance");
  const mode: Mode = stored in MODES ? (stored as Mode) : "seance";
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [active, setActive] = useState<string | null>(null);

  useEffect(() => {
    if (!box.current) return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(box.current);
    return () => observer.disconnect();
  }, []);

  const byValue = report.total.basis === "value";
  const tiles = useMemo(() => {
    const merged = new Map<string, Tile & { latent: number | null; spark: number[] }>();
    for (const p of report.positions) {
      const tile = merged.get(p.isin) ?? {
        isin: p.isin,
        name: p.name,
        size: 0,
        value: 0 as number | null,
        cost: 0,
        latent: 0 as number | null,
        spark: p.spark,
        changes: { seance: p.quote?.change ?? null, mois: null, achat: null },
      };
      tile.size += byValue ? (p.value ?? 0) : p.cost;
      tile.value = tile.value == null || p.value == null ? null : tile.value + p.value;
      tile.latent = tile.latent == null || p.latent == null ? null : tile.latent + p.latent;
      tile.cost += p.cost;
      merged.set(p.isin, tile);
    }
    return [...merged.values()]
      .map((tile) => ({
        ...tile,
        changes: {
          seance: tile.changes.seance,
          mois:
            tile.spark.length > 1 && tile.spark[0] > 0
              ? tile.spark[tile.spark.length - 1] / tile.spark[0] - 1
              : null,
          achat: tile.latent != null && tile.cost > 0 ? tile.latent / tile.cost : null,
        },
      }))
      .filter((tile) => tile.size > 0)
      .sort((a, b) => b.size - a.size);
  }, [report.positions, byValue]);

  if (tiles.length < 2) return null;
  const total = tiles.reduce((sum, tile) => sum + tile.size, 0);
  const height = Math.round(Math.min(460, Math.max(280, width * 0.42)));
  const rects = layout(
    tiles.map((tile) => tile.size),
    { x: 0, y: 0, w: width, h: height },
  );
  const { steps } = MODES[mode];
  const shown = tiles.find((tile) => tile.isin === active);

  return (
    <>
      <div className="mb-3 flex flex-wrap gap-1" role="group" aria-label="Variation représentée">
        {(Object.keys(MODES) as Mode[]).map((id) => (
          <button
            key={id}
            type="button"
            aria-pressed={mode === id}
            onClick={() => setMode(id)}
            className={`rounded-md px-3 py-1 text-sm ${
              mode === id ? "bg-accent text-surface" : "text-muted hover:bg-accent-soft"
            }`}
          >
            {MODES[id].label}
          </button>
        ))}
      </div>

      <div ref={box} className="relative" style={{ height }} onPointerLeave={() => setActive(null)}>
        {width > 0 &&
          tiles.map((tile, i) => {
            const rect = rects[i];
            const change = tile.changes[mode];
            const step = stepOf(change, steps);
            const w = rect.w - GAP;
            const h = rect.h - GAP;
            const name = h >= 40 ? fitting(tile.name, w - 12) : "";
            const figure = w >= 58 && h >= 22;
            return (
              <a
                key={tile.isin}
                href={`#/titre/${tile.isin}`}
                aria-label={`${tile.name} : ${percent(tile.size / total)} du portefeuille, ${
                  change == null ? "variation inconnue" : signedPercent(change)
                } (${MODES[mode].label.toLowerCase()})`}
                onPointerEnter={() => setActive(tile.isin)}
                onFocus={() => setActive(tile.isin)}
                onBlur={() => setActive(null)}
                className="absolute overflow-hidden rounded-[3px] px-1.5 py-1 text-[13px] leading-tight"
                style={{
                  left: rect.x + GAP / 2,
                  top: rect.y + GAP / 2,
                  width: Math.max(0, w),
                  height: Math.max(0, h),
                  background: fill(step),
                  color: ink(step),
                  filter: active === tile.isin ? "brightness(1.08)" : undefined,
                }}
              >
                {name && <span className="block font-medium">{name}</span>}
                {figure && (
                  <span className="num block">{change == null ? "—" : signedPercent(change)}</span>
                )}
              </a>
            );
          })}
      </div>

      <div className="mt-3 flex flex-wrap items-start justify-between gap-x-8 gap-y-2 text-sm">
        <p className="min-h-[1.5em]" aria-live="polite">
          {shown ? (
            <>
              <span className="font-medium">{shown.name}</span>{" "}
              <span className="num">
                {byValue ? euro(shown.value) : euro(shown.cost)}, {percent(shown.size / total)}
              </span>
              <span className="text-muted">
                {" "}
                · séance <span className="num text-ink">{signedPercent(shown.changes.seance)}</span> · 30
                jours <span className="num text-ink">{signedPercent(shown.changes.mois)}</span> · depuis
                l'achat <span className="num text-ink">{signedPercent(shown.changes.achat)}</span>
              </span>
            </>
          ) : (
            <span className="text-muted">
              Taille : poids dans le portefeuille{byValue ? "" : " (au prix de revient)"}. Survoler
              une tuile pour le détail, cliquer pour ouvrir le titre.
            </span>
          )}
        </p>
        <Scale steps={steps} />
      </div>
    </>
  );
}

/** The seven steps of the scale, with the bounds of the outer ones. */
function Scale({ steps }: { steps: [number, number, number] }) {
  const bound = percent(steps[2]);
  return (
    <div className="flex items-center gap-2 text-xs text-muted" aria-hidden="true">
      <span className="num">−{bound} et moins</span>
      <span className="flex gap-[2px]">
        {[-3, -2, -1, 0, 1, 2, 3].map((step) => (
          <span key={step} className="h-3 w-5 rounded-[2px]" style={{ background: fill(step) }} />
        ))}
      </span>
      <span className="num">+{bound} et plus</span>
    </div>
  );
}

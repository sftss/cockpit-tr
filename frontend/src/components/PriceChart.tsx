import {
  AreaSeries,
  CandlestickSeries,
  createChart,
  createSeriesMarkers,
  HistogramSeries,
  LineSeries,
  LineStyle,
  type ISeriesApi,
  type SeriesMarker,
  type SeriesType,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef, useState } from "react";
import type { ChartData } from "../api";

type Props = {
  chart: ChartData;
  candles: boolean;
  showTrades: boolean;
  format: (value: number) => string;
  /** A horizontal reference, e.g. the average cost of the position. */
  reference?: { value: number; label: string };
  label: string;
};

type Readout = {
  open: number | null;
  high: number | null;
  low: number | null;
  close: number;
  volume: number | null;
  averages: (number | null)[];
};

const cssVar = (name: string) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim();

// The library draws times in UTC: shift stamps to local time.
const local = (seconds: number) =>
  (seconds - new Date(seconds * 1000).getTimezoneOffset() * 60) as UTCTimestamp;

const compact = new Intl.NumberFormat("fr-FR", { notation: "compact", maximumFractionDigits: 1 });

/** Colours of the two moving averages: one hue, one neutral, told apart in the legend. */
const AVERAGE_COLORS = ["--chart-2", "--muted"] as const;

/**
 * Price of one instrument: bars or a curve, volume underneath on its own scale,
 * moving averages, and the user's purchases and sales marked on their day.
 */
export function PriceChart({ chart: data, candles, showTrades, format, reference, label }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<Readout | null>(null);

  // Strictly increasing times only: the library refuses anything else.
  const points = data.points.filter((p, i, all) => i === 0 || p.time > all[i - 1].time);
  const whole = points.filter((p) => p.open != null && p.high != null && p.low != null);
  const asCandles = candles && whole.length * 2 > points.length;
  const hasVolume = points.some((p) => (p.volume ?? 0) > 0);
  const height = hasVolume ? 440 : 340;
  const key = JSON.stringify([
    data.isin,
    data.range,
    data.currency,
    points.length,
    points.at(-1),
    data.trades.length,
  ]);

  useEffect(() => {
    if (!box.current || points.length < 2) return;
    const up = cssVar("--chart-1");
    const down = cssVar("--chart-down");
    const chart = createChart(box.current, {
      autoSize: true,
      height,
      layout: {
        background: { color: "transparent" },
        textColor: cssVar("--muted"),
        fontFamily: getComputedStyle(document.body).fontFamily,
        attributionLogo: true,
        panes: { separatorColor: cssVar("--line"), enableResize: false },
      },
      grid: { vertLines: { visible: false }, horzLines: { color: cssVar("--line") } },
      rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.12, bottom: 0.08 } },
      timeScale: {
        borderVisible: false,
        timeVisible: data.intraday,
        secondsVisible: false,
        fixLeftEdge: true,
        fixRightEdge: true,
      },
      localization: { locale: "fr-FR" },
      // The page scrolls with the wheel; the chart is dragged, not zoomed by accident.
      handleScroll: { mouseWheel: false, pressedMouseMove: true },
      handleScale: { mouseWheel: false, pinch: true, axisPressedMouseMove: false },
    });

    // Prices and volume do not share a unit: each series says how its axis is written.
    const priceFormat = { type: "custom" as const, formatter: format, minMove: 0.0001 };
    let main: ISeriesApi<SeriesType>;
    if (asCandles) {
      // Rising bars hollow, falling bars filled: the direction never rests on colour alone.
      main = chart.addSeries(CandlestickSeries, {
        upColor: cssVar("--paper"),
        downColor: down,
        borderUpColor: up,
        borderDownColor: down,
        wickUpColor: up,
        wickDownColor: down,
        priceLineVisible: false,
        priceFormat,
      });
      main.setData(
        points.map((p) => ({
          time: local(p.time) as Time,
          open: p.open ?? p.value,
          high: p.high ?? p.value,
          low: p.low ?? p.value,
          close: p.value,
        })),
      );
    } else {
      main = chart.addSeries(AreaSeries, {
        lineColor: up,
        topColor: `${up}33`,
        bottomColor: `${up}05`,
        lineWidth: 2,
        priceLineVisible: false,
        priceFormat,
      });
      main.setData(points.map((p) => ({ time: local(p.time) as Time, value: p.value })));
    }

    const averages = data.averages.map((average, i) => {
      const line = chart.addSeries(LineSeries, {
        color: cssVar(AVERAGE_COLORS[i] ?? "--muted"),
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
        priceFormat,
      });
      line.setData(average.points.map((p) => ({ time: local(p.time) as Time, value: p.value })));
      return line;
    });

    let volume: ISeriesApi<"Histogram"> | null = null;
    if (hasVolume) {
      volume = chart.addSeries(
        HistogramSeries,
        {
          color: `${cssVar("--muted")}80`,
          priceFormat: { type: "custom", formatter: (v: number) => compact.format(v), minMove: 1 },
          priceLineVisible: false,
          lastValueVisible: false,
        },
        1,
      );
      volume.setData(points.map((p) => ({ time: local(p.time) as Time, value: p.volume ?? 0 })));
      const [pricePane, volumePane] = chart.panes();
      pricePane.setStretchFactor(4);
      volumePane.setStretchFactor(1);
    }

    if (showTrades && data.trades.length > 0) {
      // One mark per bar and side: an arrow below the bar for purchases, above it for sales.
      const groups = new Map<string, { time: number; side: string; count: number }>();
      for (const trade of data.trades) {
        const id = `${trade.time}-${trade.side}`;
        const group = groups.get(id) ?? { time: trade.time, side: trade.side, count: 0 };
        group.count += 1;
        groups.set(id, group);
      }
      const ink = cssVar("--ink");
      const marks: SeriesMarker<Time>[] = [...groups.values()]
        .sort((a, b) => a.time - b.time)
        .map((group) => ({
          time: local(group.time) as Time,
          position: group.side === "achat" ? "belowBar" : "aboveBar",
          shape: group.side === "achat" ? "arrowUp" : "arrowDown",
          color: ink,
          text: (group.side === "achat" ? "A" : "V") + (group.count > 1 ? `×${group.count}` : ""),
        }));
      createSeriesMarkers(main, marks);
    }

    if (reference) {
      main.createPriceLine({
        price: reference.value,
        color: cssVar("--muted"),
        lineWidth: 1,
        lineStyle: LineStyle.Dotted,
        axisLabelVisible: true,
        title: reference.label,
      });
    }
    chart.timeScale().fitContent();

    const byTime = new Map(points.map((p) => [local(p.time) as number, p]));
    chart.subscribeCrosshairMove((param) => {
      const point = param.time == null ? undefined : byTime.get(param.time as number);
      if (!point) return setHover(null);
      setHover({
        open: point.open,
        high: point.high,
        low: point.low,
        close: point.value,
        volume: point.volume,
        averages: averages.map((line) => {
          const value = param.seriesData.get(line) as { value?: number } | undefined;
          return value?.value ?? null;
        }),
      });
    });
    return () => chart.remove();
    // `key` stands for the data; redraw only when it really changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, asCandles, showTrades, height, reference?.value]);

  const last = points.at(-1);
  const shown: Readout | null =
    hover ??
    (last
      ? {
          open: last.open,
          high: last.high,
          low: last.low,
          close: last.value,
          volume: last.volume,
          averages: data.averages.map((average) => average.points.at(-1)?.value ?? null),
        }
      : null);
  const figure = (name: string, value: number | null, text?: string) =>
    value == null ? null : (
      <span>
        <span className="text-muted">{name}</span>{" "}
        <span className="num">{text ?? format(value)}</span>
      </span>
    );

  return (
    <figure aria-label={label}>
      {shown && (
        <figcaption className="mb-2 flex flex-wrap gap-x-5 gap-y-1 text-sm">
          {asCandles && figure("Ouverture", shown.open)}
          {asCandles && figure("Plus haut", shown.high)}
          {asCandles && figure("Plus bas", shown.low)}
          {figure(asCandles ? "Clôture" : "Cours", shown.close)}
          {figure("Volume", shown.volume, shown.volume == null ? "" : compact.format(shown.volume))}
          {data.averages.map((average, i) => (
            <span key={average.window} className="flex items-center gap-2">
              <span
                aria-hidden="true"
                className="inline-block w-5 border-t-2"
                style={{ borderColor: `var(${AVERAGE_COLORS[i] ?? "--muted"})` }}
              />
              <span className="text-muted">{average.label}</span>
              <span className="num">
                {shown.averages[i] == null ? "—" : format(shown.averages[i] as number)}
              </span>
            </span>
          ))}
        </figcaption>
      )}
      <div ref={box} style={{ height }} />
    </figure>
  );
}

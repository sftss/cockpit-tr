import {
  AreaSeries,
  createChart,
  LineSeries,
  LineStyle,
  LineType,
  type ISeriesApi,
  type SeriesType,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef, useState } from "react";

export type ChartSeries = {
  name: string;
  /** time: seconds since the epoch (intraday) or "YYYY-MM-DD" (daily). */
  points: { time: number | string; value: number }[];
  style: "area" | "line" | "steps";
  /** First or second series colour; the two are distinct for colour-blind readers. */
  tone: 1 | 2;
};

type Props = {
  series: ChartSeries[];
  format: (value: number) => string;
  intraday?: boolean;
  height?: number;
  /** A horizontal reference, e.g. the average cost of the position. */
  reference?: { value: number; label: string };
  label: string;
};

const cssVar = (name: string) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim();

// The library draws times in UTC: shift intraday stamps to local time.
const local = (seconds: number) =>
  (seconds - new Date(seconds * 1000).getTimezoneOffset() * 60) as UTCTimestamp;

/**
 * Time series with a crosshair. One axis, thin lines; with two series the
 * legend above the plot names them and shows the values under the cursor.
 */
export function TimeChart({ series, format, intraday, height = 300, reference, label }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<(number | null)[] | null>(null);
  const key = JSON.stringify(series.map((s) => [s.name, s.points.length, s.points.at(-1)]));

  useEffect(() => {
    if (!box.current) return;
    const colors = { 1: cssVar("--chart-1"), 2: cssVar("--chart-2") };
    const chart = createChart(box.current, {
      autoSize: true,
      height,
      layout: {
        background: { color: "transparent" },
        textColor: cssVar("--muted"),
        fontFamily: getComputedStyle(document.body).fontFamily,
        attributionLogo: true,
      },
      grid: { vertLines: { visible: false }, horzLines: { color: cssVar("--line") } },
      rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.12, bottom: 0.08 } },
      timeScale: {
        borderVisible: false,
        timeVisible: !!intraday,
        secondsVisible: false,
        fixLeftEdge: true,
        fixRightEdge: true,
      },
      localization: { locale: "fr-FR", priceFormatter: format },
      // The page scrolls with the wheel; the chart is dragged, not zoomed by accident.
      handleScroll: { mouseWheel: false, pressedMouseMove: true },
      handleScale: { mouseWheel: false, pinch: true, axisPressedMouseMove: false },
    });

    const drawn: ISeriesApi<SeriesType>[] = series.map((s) => {
      const color = colors[s.tone];
      const common = { color, lineWidth: 2 as const, priceLineVisible: false };
      const api =
        s.style === "area"
          ? chart.addSeries(AreaSeries, {
              lineColor: color,
              topColor: `${color}33`,
              bottomColor: `${color}05`,
              lineWidth: 2,
              priceLineVisible: false,
            })
          : chart.addSeries(LineSeries, {
              ...common,
              lineType: s.style === "steps" ? LineType.WithSteps : LineType.Simple,
              lineStyle: s.style === "steps" ? LineStyle.Dashed : LineStyle.Solid,
              lastValueVisible: false,
            });
      api.setData(
        s.points.map((p) => ({
          time: (typeof p.time === "number" ? local(p.time) : p.time) as Time,
          value: p.value,
        })),
      );
      return api;
    });

    if (reference && drawn[0]) {
      drawn[0].createPriceLine({
        price: reference.value,
        color: cssVar("--muted"),
        lineWidth: 1,
        lineStyle: LineStyle.Dotted,
        axisLabelVisible: true,
        title: reference.label,
      });
    }
    chart.timeScale().fitContent();

    chart.subscribeCrosshairMove((param) => {
      if (!param.time) return setHover(null);
      setHover(
        drawn.map((api) => {
          const point = param.seriesData.get(api) as { value?: number } | undefined;
          return point?.value ?? null;
        }),
      );
    });
    return () => chart.remove();
    // `key` stands for the data; redraw only when it really changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, intraday, height, reference?.value]);

  const shown = hover ?? series.map((s) => s.points.at(-1)?.value ?? null);
  return (
    <figure aria-label={label}>
      {series.length > 1 && (
        <figcaption className="mb-2 flex flex-wrap gap-x-6 gap-y-1 text-sm">
          {series.map((s, i) => (
            <span key={s.name} className="flex items-center gap-2">
              <span
                aria-hidden="true"
                className="inline-block w-5 border-t-2"
                style={{
                  borderColor: `var(--chart-${s.tone})`,
                  borderTopStyle: s.style === "steps" ? "dashed" : "solid",
                }}
              />
              <span className="text-muted">{s.name}</span>
              <span className="num">{shown[i] == null ? "—" : format(shown[i] as number)}</span>
            </span>
          ))}
        </figcaption>
      )}
      <div ref={box} style={{ height }} />
    </figure>
  );
}

import { useEffect, useState } from "react";
import { api, type Performance } from "../api";
import { date, signedPercent } from "../format";
import { usePreference } from "../preferences";
import { TimeChart } from "./TimeChart";
import { Notice, Section, inputClass } from "./ui";

const SPANS = [
  ["3m", "3 mois", 92],
  ["1a", "1 an", 366],
  ["tout", "Tout", Infinity],
] as const;

const points100 = new Intl.NumberFormat("fr-FR", {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
  signDisplay: "always",
});

/**
 * Performance of the portfolio beside a benchmark, both starting from zero at
 * the beginning of the period shown. Money added or withdrawn is set aside.
 */
export function PerformanceChart({ stamp }: { stamp: string | null }) {
  const [choice, setChoice] = usePreference<string>("performance.indice", "");
  const [span, setSpan] = usePreference<string>("performance.periode", "tout");
  const [data, setData] = useState<Performance | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .performance(choice || undefined)
      .then((result) => alive && setData(result))
      .catch(() => alive && setData(null));
    return () => {
      alive = false;
    };
  }, [choice, stamp]);

  if (!data || !data.priced || data.points.length < 2) return null;

  const last = data.points[data.points.length - 1];
  const days = (SPANS.find(([id]) => id === span) ?? SPANS[2])[2];
  const from = Number.isFinite(days)
    ? new Date(new Date(last.date).getTime() - days * 86_400_000).toISOString().slice(0, 10)
    : "";
  const inSpan = data.points.filter((p) => p.date >= from);
  // Both curves start where the benchmark has its first price in the period.
  const start = inSpan.find((p) => p.benchmark != null && p.benchmark > 0) ?? inSpan[0];
  const shown = inSpan.filter((p) => p.date >= start.date);
  const mine = shown.map((p) => ({ time: p.date, value: p.portfolio / start.portfolio - 1 }));
  const theirs = start.benchmark
    ? shown
        .filter((p) => p.benchmark != null)
        .map((p) => ({ time: p.date, value: (p.benchmark as number) / (start.benchmark as number) - 1 }))
    : [];
  const mineLast = mine.at(-1)?.value ?? 0;
  const theirsLast = theirs.at(-1)?.value;

  return (
    <Section title="Performance comparée">
      <div className="mb-3 flex flex-wrap items-center gap-x-6 gap-y-2">
        <div className="flex flex-wrap gap-1" role="group" aria-label="Période">
          {SPANS.map(([id, label]) => (
            <button
              key={id}
              type="button"
              aria-pressed={span === id}
              onClick={() => setSpan(id)}
              className={`rounded-md px-3 py-1 text-sm ${
                span === id ? "bg-accent text-surface" : "text-muted hover:bg-accent-soft"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2 text-sm">
          <span className="text-muted">Comparé à</span>
          <select
            value={data.benchmark.id}
            onChange={(e) => setChoice(e.target.value)}
            className={inputClass}
          >
            {data.benchmarks.map((benchmark) => (
              <option key={benchmark.id} value={benchmark.id}>
                {benchmark.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {data.error && (
        <div className="mb-4">
          <Notice tone="error">Indice indisponible : {data.error}.</Notice>
        </div>
      )}

      <TimeChart
        label={`Performance du portefeuille comparée à ${data.benchmark.label}`}
        format={signedPercent}
        series={[
          { name: "Portefeuille", points: mine, style: "line", tone: 1 },
          ...(theirs.length > 1
            ? [{ name: data.benchmark.label, points: theirs, style: "line" as const, tone: 2 as const }]
            : []),
        ]}
      />
      <p className="mt-3 max-w-[80ch] text-sm text-muted">
        Du {date(start.date)} au {date(last.date)} : portefeuille {signedPercent(mineLast)}
        {theirsLast != null &&
          `, ${data.benchmark.label} ${signedPercent(theirsLast)}, soit ${points100.format(
            (mineLast - theirsLast) * 100,
          )} point${Math.abs(mineLast - theirsLast) >= 0.02 ? "s" : ""} d'écart`}
        . Les achats et les ventes sont neutralisés jour par jour : la courbe mesure l'évolution des
        titres détenus, pas l'argent ajouté. Hors frais d'ordre et dividendes reçus ; un fonds qui
        réinvestit ses dividendes est donc légèrement avantagé. Une performance passée ne dit rien
        de la suite.
      </p>
    </Section>
  );
}

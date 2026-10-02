import { useEffect, useState } from "react";
import { api, type ValueHistory as History } from "../api";
import { date, euro, euroRound, signedEuro } from "../format";
import { TimeChart } from "./TimeChart";
import { Button, Notice } from "./ui";

const SPANS = [
  ["3m", "3 mois", 92],
  ["1a", "1 an", 366],
  ["tout", "Tout", Infinity],
] as const;

/** Value of the portfolio against the net amount invested, since the first purchase. */
export function ValueHistory({ stamp }: { stamp: string | null }) {
  const [history, setHistory] = useState<History | null>(null);
  const [span, setSpan] = useState<string>("tout");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const fetchHistory = () => api.valueHistory().then(setHistory).catch(() => setHistory(null));
  useEffect(() => {
    fetchHistory();
  }, [stamp]);

  const loadPrices = async () => {
    setLoading(true);
    setMessage(null);
    try {
      const outcome = await api.loadHistory();
      if (outcome.refused) setMessage("La source de cours a refusé la requête. Réessayer plus tard.");
      else if (outcome.unreachable) setMessage("La source de cours est injoignable.");
      else if (outcome.errors.length) setMessage(`Cours manquants : ${outcome.errors.join(" ; ")}`);
      await fetchHistory();
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  if (!history || history.points.length === 0) return null;
  const priced = history.points.some((p) => p.at_cost < p.value || p.value === 0);
  const last = history.points[history.points.length - 1];

  if (!priced) {
    return (
      <>
        <p className="mb-4 max-w-[70ch] text-muted">
          La courbe a besoin de l'historique des cours depuis le {date(history.points[0].date)}.
          Le chargement interroge la source de cours pour chaque titre déjà détenu et prend environ
          une minute.
        </p>
        <Button onClick={loadPrices} disabled={loading}>
          {loading ? "Chargement en cours…" : "Charger l'historique des cours"}
        </Button>
        {message && (
          <div className="mt-4">
            <Notice tone="error">{message}</Notice>
          </div>
        )}
      </>
    );
  }

  const days = SPANS.find(([id]) => id === span)![2];
  const from = Number.isFinite(days)
    ? new Date(new Date(last.date).getTime() - days * 86_400_000).toISOString().slice(0, 10)
    : "";
  const points = history.points.filter((p) => p.date >= from);

  return (
    <>
      <div className="mb-3 flex flex-wrap items-center gap-1" role="group" aria-label="Période">
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
      <TimeChart
        label="Valeur du portefeuille et capital net engagé"
        format={euroRound}
        series={[
          {
            name: "Valeur",
            points: points.map((p) => ({ time: p.date, value: p.value })),
            style: "area",
            tone: 1,
          },
          {
            name: "Capital net engagé",
            points: points.map((p) => ({ time: p.date, value: p.invested })),
            style: "steps",
            tone: 2,
          },
        ]}
      />
      <p className="mt-3 max-w-[75ch] text-sm text-muted">
        Au {date(last.date)} : {euro(last.value)} pour {euro(last.invested)} engagés, soit{" "}
        {signedEuro(last.value - last.invested)}. Hors or, espèces et dividendes.
        {last.at_cost > 0 &&
          ` ${euro(last.at_cost)} sont comptés au prix de revient, faute de cours${
            history.unpriced.length ? ` (${history.unpriced.join(", ")})` : ""
          }.`}
      </p>
      {message && (
        <div className="mt-4">
          <Notice tone="error">{message}</Notice>
        </div>
      )}
    </>
  );
}

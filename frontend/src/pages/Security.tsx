import { useEffect, useState } from "react";
import { api, type ChartData, type Report } from "../api";
import { TimeChart } from "../components/TimeChart";
import { Notice, PageTitle, Result, Section, TableWrap } from "../components/ui";
import {
  accountName,
  amount,
  clock,
  delayLabel,
  euro,
  quantity,
  signedEuro,
  signedPercent,
} from "../format";

const RANGES = [
  ["1j", "Jour"],
  ["5j", "5 jours"],
  ["1m", "1 mois"],
  ["6m", "6 mois"],
  ["1a", "1 an"],
  ["5a", "5 ans"],
  ["max", "Tout"],
] as const;

export function Security({ isin, report }: { isin: string; report: Report }) {
  const [range, setRange] = useState<string>("1j");
  const [chart, setChart] = useState<ChartData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const positions = report.positions.filter((p) => p.isin === isin);
  const first = positions[0];
  const quote = first?.quote ?? null;

  useEffect(() => {
    let alive = true;
    const load = () =>
      api
        .chart(isin, range)
        .then((data) => {
          if (!alive) return;
          setChart(data);
          setError(null);
        })
        .catch((e: Error) => alive && setError(e.message));
    load();
    // The day's chart follows the market while the page is in front.
    const timer =
      range === "1j"
        ? window.setInterval(() => document.visibilityState === "visible" && load(), 60_000)
        : undefined;
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [isin, range]);

  if (!first) {
    return (
      <PageTitle lead="Ce titre n'est plus en portefeuille, ou son code est inconnu.">
        Titre introuvable
      </PageTitle>
    );
  }

  const currency = chart?.currency ?? quote?.currency ?? "EUR";
  const inEuros = currency === "EUR";
  const averageCost = positions.length === 1 ? first.average_cost : null;

  return (
    <>
      <p className="mb-3 text-sm">
        <a className="text-accent underline" href="#/portefeuille">
          Portefeuille
        </a>
      </p>
      <PageTitle
        lead={
          <>
            {isin}
            {chart && `, ${chart.symbol} à ${chart.exchange}, ${delayLabel(chart.delay_minutes)}`}
          </>
        }
      >
        {first.name}
      </PageTitle>

      {quote && (
        <p className="mb-6 flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <span className="num font-display text-3xl">{amount(quote.price, quote.currency)}</span>
          {!inEuros && <span className="num text-muted">soit {euro(quote.price_eur)}</span>}
          <Result value={quote.change}>{signedPercent(quote.change)} sur la séance</Result>
          <span className="text-sm text-muted">cours de {clock(quote.market_time)}</span>
        </p>
      )}

      <div className="mb-3 flex flex-wrap gap-1" role="group" aria-label="Période du graphique">
        {RANGES.map(([id, label]) => (
          <button
            key={id}
            type="button"
            aria-pressed={range === id}
            onClick={() => setRange(id)}
            className={`rounded-md px-3 py-1 text-sm ${
              range === id ? "bg-accent text-surface" : "text-muted hover:bg-accent-soft"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {error ? (
        <Notice tone="error">
          Graphique indisponible : {error}. Le symbole de cotation se corrige dans la page{" "}
          <a className="underline" href="#/donnees">
            Données
          </a>
          .
        </Notice>
      ) : chart && chart.points.length > 1 ? (
        <TimeChart
          label={`Cours de ${first.name}`}
          intraday={chart.intraday}
          format={(v) => amount(v, currency)}
          series={[{ name: "Cours", points: chart.points, style: "area", tone: 1 }]}
          reference={
            inEuros && averageCost != null && !chart.intraday
              ? { value: averageCost, label: "coût moyen" }
              : undefined
          }
        />
      ) : chart ? (
        <Notice>Pas de cotation sur cette période (marché fermé, ou titre trop récent).</Notice>
      ) : (
        <div style={{ height: 300 }} className="text-sm text-muted">
          Chargement du graphique…
        </div>
      )}

      <div className="mt-10">
        <Section title="Ma position">
          <TableWrap>
            <table className="data max-w-3xl">
              <thead>
                <tr>
                  <th>Compte</th>
                  <th>Quantité</th>
                  <th>Coût moyen</th>
                  <th>Prix de revient</th>
                  <th>Valeur</th>
                  <th>Résultat latent</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((p) => (
                  <tr key={p.account}>
                    <td>{accountName(p.account)}</td>
                    <td className="num">{quantity(p.shares)}</td>
                    <td className="num">{euro(p.average_cost)}</td>
                    <td className="num">{euro(p.cost)}</td>
                    <td className="num">{euro(p.value)}</td>
                    <td>
                      <Result value={p.latent}>
                        {signedEuro(p.latent)}{" "}
                        <span className="text-xs">({signedPercent(p.latent_pct)})</span>
                      </Result>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        </Section>
      </div>
    </>
  );
}

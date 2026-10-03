import { useEffect, useState } from "react";
import { api, type ChartData, type Report, type SecurityData, type SecurityStats } from "../api";
import { PriceChart } from "../components/PriceChart";
import { Notice, PageTitle, Result, Section, TableWrap } from "../components/ui";
import {
  accountName,
  amount,
  clock,
  compact,
  date,
  delayLabel,
  euro,
  plural,
  quantity,
  signedEuro,
  signedPercent,
} from "../format";
import { usePreference } from "../preferences";

const RANGES = [
  ["1j", "Jour"],
  ["5j", "5 jours"],
  ["1m", "1 mois"],
  ["6m", "6 mois"],
  ["1a", "1 an"],
  ["5a", "5 ans"],
  ["max", "Tout"],
] as const;

const SHORT_LIST = 10; // trades shown before asking for the whole list

const toggle = (on: boolean) =>
  `rounded-md px-3 py-1 text-sm ${on ? "bg-accent text-surface" : "text-muted hover:bg-accent-soft"}`;

export function Security({ isin, report }: { isin: string; report: Report }) {
  const [stored, setRange] = usePreference<string>("titre.periode", "1a");
  const range = RANGES.some(([id]) => id === stored) ? stored : "1a";
  const [inEuros, setInEuros] = usePreference<boolean>("titre.euros", true);
  const [candles, setCandles] = usePreference<boolean>("titre.chandeliers", true);
  const [showTrades, setShowTrades] = usePreference<boolean>("titre.ordres", true);
  const [chart, setChart] = useState<ChartData | null>(null);
  const [security, setSecurity] = useState<SecurityData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ticketError, setTicketError] = useState<string | null>(null);
  const [unknown, setUnknown] = useState(false);
  const [allTrades, setAllTrades] = useState(false);
  const positions = report.positions.filter((p) => p.isin === isin);
  const first = positions[0];
  const quote = first?.quote ?? null;

  useEffect(() => {
    let alive = true;
    const load = () =>
      api
        .chart(isin, range, inEuros)
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
  }, [isin, range, inEuros]);

  useEffect(() => {
    let alive = true;
    api
      .security(isin, inEuros)
      .then((data) => alive && setSecurity(data))
      .catch(() => alive && setUnknown(true));
    return () => {
      alive = false;
    };
  }, [isin, inEuros, report.last_import]);

  /** A draft ticket on this title; the page of tickets takes over from there. */
  const prepare = async (side: "BUY" | "SELL") => {
    try {
      await api.createTicket({ isin, side, ...(first ? { account: first.account } : {}) });
      window.location.hash = "#/tickets";
    } catch (e) {
      setTicketError((e as Error).message);
    }
  };

  if (unknown) {
    return (
      <PageTitle lead="Aucun titre de ce code n'a été acheté ou vendu dans les transactions importées.">
        Titre introuvable
      </PageTitle>
    );
  }

  const name = security?.name ?? first?.name ?? isin;
  const currency = chart?.currency ?? quote?.currency ?? "EUR";
  const foreign = chart != null && chart.native_currency !== "EUR";
  const averageCost = positions.length === 1 ? first.average_cost : null;
  const stats = security?.stats ?? null;
  const trades = security?.trades ?? [];
  const drawn = chart != null && chart.points.length > 1;
  const buys = trades.filter((t) => t.side === "achat");
  const sells = trades.filter((t) => t.side === "vente");
  const sum = (list: typeof trades) => list.reduce((total, t) => total + t.amount, 0);

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
            {security && !security.held && ". Ligne soldée : ce titre n'est plus en portefeuille."}
          </>
        }
      >
        {name}
      </PageTitle>

      {quote ? (
        <p className="mb-6 flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <span className="num font-display text-3xl">{amount(quote.price, quote.currency)}</span>
          {quote.currency !== "EUR" && (
            <span className="num text-muted">soit {euro(quote.price_eur)}</span>
          )}
          <Result value={quote.change}>{signedPercent(quote.change)} sur la séance</Result>
          <span className="text-sm text-muted">cours de {clock(quote.market_time)}</span>
        </p>
      ) : (
        stats && (
          <p className="mb-6 flex flex-wrap items-baseline gap-x-4 gap-y-1">
            <span className="num font-display text-3xl">{amount(stats.price, stats.currency)}</span>
            <span className="text-sm text-muted">dernier cours, le {date(stats.as_of)}</span>
          </p>
        )
      )}

      <p className="mb-6 flex flex-wrap gap-x-5 gap-y-1 text-sm">
        <span className="text-muted">Ticket d'ordre :</span>
        <button type="button" onClick={() => prepare("BUY")} className="text-accent hover:underline">
          préparer un achat
        </button>
        {first && (
          <button type="button" onClick={() => prepare("SELL")} className="text-accent hover:underline">
            préparer une vente
          </button>
        )}
        {ticketError && <span className="w-full text-alert">{ticketError}</span>}
      </p>

      <div className="mb-3 flex flex-wrap items-center gap-x-6 gap-y-2">
        <div className="flex flex-wrap gap-1" role="group" aria-label="Période du graphique">
          {RANGES.map(([id, label]) => (
            <button
              key={id}
              type="button"
              aria-pressed={range === id}
              onClick={() => setRange(id)}
              className={toggle(range === id)}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="flex gap-1" role="group" aria-label="Forme du graphique">
          <button type="button" aria-pressed={candles} onClick={() => setCandles(true)} className={toggle(candles)}>
            Chandeliers
          </button>
          <button type="button" aria-pressed={!candles} onClick={() => setCandles(false)} className={toggle(!candles)}>
            Courbe
          </button>
        </div>
        {foreign && (
          <div className="flex gap-1" role="group" aria-label="Devise du graphique">
            <button type="button" aria-pressed={inEuros} onClick={() => setInEuros(true)} className={toggle(inEuros)}>
              En euros
            </button>
            <button type="button" aria-pressed={!inEuros} onClick={() => setInEuros(false)} className={toggle(!inEuros)}>
              En {chart.native_currency}
            </button>
          </div>
        )}
        {trades.length > 0 && (
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={showTrades}
              onChange={(e) => setShowTrades(e.target.checked)}
              className="accent-[var(--accent)]"
            />
            Mes ordres
          </label>
        )}
      </div>

      {error ? (
        <Notice tone="error">
          Graphique indisponible : {error}. Le symbole de cotation se corrige dans la page{" "}
          <a className="underline" href="#/donnees">
            Données
          </a>
          .
        </Notice>
      ) : drawn ? (
        <>
          <PriceChart
            label={`Cours de ${name}`}
            chart={chart}
            candles={candles}
            showTrades={showTrades}
            format={(v) => amount(v, currency)}
            reference={
              currency === "EUR" && averageCost != null && !chart.intraday
                ? { value: averageCost, label: "coût moyen" }
                : undefined
            }
          />
          <p className="mt-3 max-w-[80ch] text-sm text-muted">
            {showTrades &&
              chart.trades.length > 0 &&
              "A : achat, V : vente, sur le jour de l'ordre et non à son prix. "}
            {foreign &&
              inEuros &&
              `Cours convertis au taux de change de chaque jour : une reconstitution, ce titre est coté en ${chart.native_currency}. `}
            {chart.averages.length === 0 &&
              !chart.intraday &&
              "Pas de moyenne mobile sur cette période. "}
            {chart.intraday && "Les moyennes mobiles s'affichent à partir d'un mois. "}
          </p>
        </>
      ) : chart ? (
        <Notice>Pas de cotation sur cette période (marché fermé, ou titre trop récent).</Notice>
      ) : (
        <div style={{ height: 340 }} className="text-sm text-muted">
          Chargement du graphique…
        </div>
      )}

      <div className="mt-10">
        {stats ? (
          <KeyFigures stats={stats} />
        ) : (
          security?.stats_error && (
            <Section title="Chiffres clés">
              <Notice>Indisponibles : {security.stats_error}.</Notice>
            </Section>
          )
        )}

        {positions.length > 0 && (
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
        )}

        {trades.length > 0 && (
          <Section
            title="Mes ordres sur ce titre"
            note="Tels qu'exécutés chez Trade Republic, en euros. Les exécutions de plan d'investissement n'ont pas de frais."
          >
            <TableWrap>
              <table className="data trades max-w-3xl">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Sens</th>
                    <th>Compte</th>
                    <th>Quantité</th>
                    <th>Cours</th>
                    <th>Montant</th>
                    <th>Frais</th>
                  </tr>
                </thead>
                <tbody>
                  {[...trades]
                    .reverse()
                    .slice(0, allTrades ? undefined : SHORT_LIST)
                    .map((t) => (
                    <tr key={t.datetime + t.account + t.side}>
                      <td className="num">{date(t.date)}</td>
                      <td>{t.side === "achat" ? "Achat" : "Vente"}</td>
                      <td>{accountName(t.account)}</td>
                      <td className="num">{quantity(t.shares)}</td>
                      <td className="num">{euro(t.price)}</td>
                      <td className="num">{euro(t.amount)}</td>
                      <td className="num">{euro(t.fee)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableWrap>
            <p className="mt-3 text-sm text-muted">
              {plural(buys.length, "achat", "achats")} pour {euro(sum(buys))}
              {sells.length > 0 && `, ${plural(sells.length, "vente", "ventes")} pour ${euro(sum(sells))}`}
              , {euro(trades.reduce((total, t) => total + t.fee, 0))} de frais.{" "}
              {trades.length > SHORT_LIST && (
                <button
                  type="button"
                  className="text-accent underline underline-offset-4"
                  onClick={() => setAllTrades(!allTrades)}
                >
                  {allTrades ? "Ne montrer que les derniers" : `Montrer les ${trades.length} ordres`}
                </button>
              )}
            </p>
          </Section>
        )}
      </div>
    </>
  );
}

function KeyFigures({ stats }: { stats: SecurityStats }) {
  const money = (value: number | null) => amount(value, stats.currency);
  return (
    <Section
      title="Chiffres clés"
      note={`Lus dans les cours quotidiens, au ${date(stats.as_of)}, en ${stats.currency}. Variations hors dividendes.`}
    >
      <div className="grid max-w-4xl gap-x-12 gap-y-6 md:grid-cols-2">
        <div className="space-y-6">
          {stats.day_low != null && stats.day_high != null && (
            <RangeMeter
              label="Fourchette de la séance"
              low={stats.day_low}
              high={stats.day_high}
              value={stats.price}
              format={money}
            />
          )}
          <RangeMeter
            label="Fourchette sur 52 semaines"
            low={stats.year_low}
            high={stats.year_high}
            value={stats.price}
            format={money}
          />
        </div>
        <dl className="grid grid-cols-2 gap-x-8 gap-y-4 text-sm">
          <Figure label="Clôture précédente" value={money(stats.previous_close)} />
          <Figure label="Ouverture" value={money(stats.open)} />
          <Figure label="Volume de la séance" value={stats.volume == null ? "—" : compact(stats.volume)} />
          <Figure
            label="Volume moyen, 3 mois"
            value={stats.average_volume == null ? "—" : compact(stats.average_volume)}
          />
        </dl>
      </div>
      <dl className="mt-8 grid max-w-4xl grid-cols-2 gap-x-8 gap-y-4 text-sm sm:grid-cols-4">
        {stats.changes.map((c) => (
          <div key={c.label} className="border-t border-line pt-3">
            <dt className="text-muted">{c.label}</dt>
            <dd className="text-base">
              <Result value={c.change}>{signedPercent(c.change)}</Result>
            </dd>
          </div>
        ))}
      </dl>
    </Section>
  );
}

function Figure({ label, value }: { label: string; value: string }) {
  return (
    <div className="border-t border-line pt-3">
      <dt className="text-muted">{label}</dt>
      <dd className="num text-base">{value}</dd>
    </div>
  );
}

/** Where the price stands between a low and a high: a track and one mark. */
function RangeMeter({
  label,
  low,
  high,
  value,
  format,
}: {
  label: string;
  low: number;
  high: number;
  value: number;
  format: (value: number) => string;
}) {
  const share = high > low ? Math.min(1, Math.max(0, (value - low) / (high - low))) : 0.5;
  return (
    <div className="text-sm">
      <div className="mb-2 text-muted">{label}</div>
      <div
        role="img"
        aria-label={`${label} : de ${format(low)} à ${format(high)}, cours à ${Math.round(share * 100)} % de la fourchette`}
        className="relative h-1 rounded-full bg-line"
      >
        <span
          className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-accent ring-2 ring-paper"
          style={{ left: `${share * 100}%` }}
        />
      </div>
      <div className="mt-2 flex justify-between">
        <span className="num">{format(low)}</span>
        <span className="num">{format(high)}</span>
      </div>
    </div>
  );
}

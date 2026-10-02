import { useState } from "react";
import { api, type Position, type RefreshOutcome, type Report } from "../api";
import { Sparkline } from "../components/Sparkline";
import { Button, Notice, PageTitle, Result, Section, TableWrap } from "../components/ui";
import {
  accountName,
  amount,
  clock,
  date,
  delayLabel,
  euro,
  percent,
  quantity,
  signedEuro,
  signedPercent,
} from "../format";

type Props = {
  report: Report;
  reload: () => void;
  refresh: () => void;
  refreshing: boolean;
  outcome: RefreshOutcome | null;
};

export function Portfolio({ report, reload, refresh, refreshing, outcome }: Props) {
  const [error, setError] = useState<string | null>(null);

  const save = async (isin: string, price: string) => {
    try {
      setError(null);
      await api.setPrice(isin, price);
      reload();
    } catch (e) {
      setError(`Cours non enregistré : ${(e as Error).message}`);
    }
  };

  const quoted = report.positions.filter((p) => p.quote);
  const latest = quoted
    .map((p) => p.quote!.fetched_at)
    .sort()
    .at(-1);
  const live = quoted.filter((p) => p.quote!.delay_minutes === 0).length;

  return (
    <>
      <PageTitle
        lead={
          latest
            ? `Cours relevés à ${clock(latest)} : ${live} en temps réel, ${quoted.length - live} en différé. Ils se mettent à jour seuls toutes les deux minutes tant que la page est ouverte.`
            : "Aucun cours récupéré pour l'instant. Un cours peut toujours être saisi à la main."
        }
      >
        Portefeuille
      </PageTitle>

      <div className="mb-8 flex flex-wrap items-center gap-4">
        <Button onClick={refresh} disabled={refreshing}>
          {refreshing ? "Actualisation…" : "Actualiser les cours"}
        </Button>
      </div>

      {outcome && (outcome.refused || outcome.unreachable) && (
        <div className="mb-6">
          <Notice tone="error">
            {outcome.refused
              ? "La source de cours a refusé la requête. Elle sera réessayée plus tard ; en attendant, les derniers cours connus sont affichés."
              : "La source de cours est injoignable. Vérifier la connexion Internet ; les derniers cours connus sont affichés."}
          </Notice>
        </div>
      )}
      {error && (
        <div className="mb-6">
          <Notice tone="error">{error}</Notice>
        </div>
      )}
      {report.anomalies.length > 0 && (
        <div className="mb-6">
          <Notice tone="error">À vérifier dans l'export : {report.anomalies.join(" ; ")}</Notice>
        </div>
      )}

      {report.accounts.map((account) => {
        const positions = report.positions.filter((p) => p.account === account.account);
        if (positions.length === 0) return null;
        const byValue = positions[0].weight_basis === "value";
        return (
          <Section
            key={account.account}
            title={accountName(account.account)}
            note={
              byValue
                ? "Poids calculés sur la valeur."
                : "Poids calculés sur le prix de revient tant qu'il manque des cours."
            }
          >
            <TableWrap>
              <table className="data positions">
                <thead>
                  <tr>
                    <th>Titre</th>
                    <th>Quantité</th>
                    <th>Prix de revient</th>
                    <th>Cours</th>
                    <th>Séance</th>
                    <th>30 jours</th>
                    <th>Valeur</th>
                    <th>Résultat latent</th>
                    <th>Poids</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((p) => (
                    <Row key={p.isin} position={p} save={save} />
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <td>Total</td>
                    <td />
                    <td className="num">{euro(account.open_cost)}</td>
                    <td />
                    <td />
                    <td />
                    <td className="num">{euro(account.value)}</td>
                    <td>
                      <Result value={account.latent}>{signedEuro(account.latent)}</Result>
                    </td>
                    <td />
                  </tr>
                </tfoot>
              </table>
            </TableWrap>
          </Section>
        );
      })}
    </>
  );
}

function Row({ position: p, save }: { position: Position; save: (isin: string, price: string) => void }) {
  return (
    <tr>
      <td>
        <a className="underline decoration-line underline-offset-4 hover:decoration-accent" href={`#/titre/${p.isin}`}>
          {p.name}
        </a>
        <span className="block text-xs text-muted">{p.isin}</span>
      </td>
      <td className="num">{quantity(p.shares)}</td>
      <td className="num">{euro(p.cost)}</td>
      <td>{p.quote ? <QuoteCell position={p} /> : <ManualPrice position={p} save={save} />}</td>
      <td>
        <Result value={p.quote?.change ?? null}>{signedPercent(p.quote?.change)}</Result>
      </td>
      <td>
        <Sparkline values={p.spark} label={p.name} />
      </td>
      <td className="num">{euro(p.value)}</td>
      <td>
        <Result value={p.latent}>
          {signedEuro(p.latent)} <span className="text-xs">({signedPercent(p.latent_pct)})</span>
        </Result>
      </td>
      <td className="num">{percent(p.weight)}</td>
    </tr>
  );
}

function QuoteCell({ position: p }: { position: Position }) {
  const q = p.quote!;
  return (
    <span
      className="num"
      title={`${q.exchange ?? "Place inconnue"}, ${delayLabel(q.delay_minutes)}, cours de ${clock(q.market_time)}`}
    >
      {euro(q.price_eur)}
      <span className="block text-xs text-muted">
        {q.currency !== "EUR" && `${amount(q.price, q.currency)}, `}
        {q.delay_minutes === 0 ? "temps réel" : q.delay_minutes ? `différé ${q.delay_minutes} min` : "différé"}
      </span>
    </span>
  );
}

function ManualPrice({ position: p, save }: { position: Position; save: (isin: string, price: string) => void }) {
  const stored = p.price != null ? String(p.price).replace(".", ",") : "";
  const [draft, setDraft] = useState(stored);
  const commit = () => {
    const value = draft.trim();
    if (value && value !== stored) save(p.isin, value);
    else setDraft(stored);
  };
  return (
    <input
      aria-label={`Cours de ${p.name}, en euros`}
      title={p.price_date ? `Saisi le ${date(p.price_date)}` : "Aucun cours : saisir un cours en euros"}
      inputMode="decimal"
      value={draft}
      placeholder="saisir"
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
      className="num w-24 rounded-md border border-line bg-surface px-2 py-1 text-right"
    />
  );
}

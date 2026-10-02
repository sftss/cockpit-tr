import type { Report } from "../api";
import { QuarterChart } from "../components/QuarterChart";
import { ValueHistory } from "../components/ValueHistory";
import { PageTitle, Result, Section, TableWrap } from "../components/ui";
import {
  accountName,
  date,
  euro,
  percent,
  plural,
  previousQuarter,
  quarterName,
  quarterOf,
  signedEuro,
  signedPercent,
} from "../format";

export function Home({ report }: { report: Report }) {
  const current = quarterOf(new Date());
  const empty = { quarter: current, manual_orders: 0, trades: 0, order_fees: 0, deposit_fees: 0 };
  const now = report.quarters.find((q) => q.quarter === current) ?? empty;
  const before = report.quarters.find((q) => q.quarter === previousQuarter(current));
  const quarters = report.quarters.some((q) => q.quarter === current)
    ? report.quarters
    : [...report.quarters, empty];
  const { fees, flows, closed_summary: closed } = report;

  return (
    <>
      <PageTitle
        lead={
          before &&
          `Au trimestre précédent : ${plural(before.manual_orders, "ordre manuel", "ordres manuels")} et ${euro(before.order_fees)} de frais d'ordre.`
        }
      >
        {quarterName(current)} :{" "}
        {now.manual_orders === 0
          ? "aucun ordre manuel"
          : plural(now.manual_orders, "ordre manuel", "ordres manuels")}
        , {euro(now.order_fees)} de frais d'ordre
      </PageTitle>

      <Section title="Comptes">
        <TableWrap>
          <table className="data">
            <thead>
              <tr>
                <th>Compte</th>
                <th>Lignes</th>
                <th>Capital net engagé</th>
                <th>Prix de revient</th>
                <th>Valeur</th>
                <th>Résultat latent</th>
                <th>Performance</th>
                <th>Espèces (estimé)</th>
              </tr>
            </thead>
            <tbody>
              {report.accounts.map((a) => (
                <tr key={a.account}>
                  <td>{accountName(a.account)}</td>
                  <td className="num">{a.open_lines}</td>
                  <td className="num">{euro(a.net_invested)}</td>
                  <td className="num">{euro(a.open_cost)}</td>
                  <td className="num">
                    {a.value != null ? (
                      euro(a.value)
                    ) : (
                      <span className="text-muted">
                        {a.priced_lines}/{a.open_lines} cours
                      </span>
                    )}
                  </td>
                  <td>
                    <Result value={a.latent}>{signedEuro(a.latent)}</Result>
                  </td>
                  <td>
                    <Result value={a.performance}>{signedPercent(a.performance)}</Result>
                  </td>
                  <td className="num">{euro(a.cash_estimate)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
        <p className="mt-3 max-w-[75ch] text-sm text-muted">
          Le capital net engagé est ce qui a été payé en achats, moins ce qui a été reçu en ventes.
          La performance compare la valeur à ce capital ; elle s'affiche quand chaque ligne du
          compte a un cours. Les espèces sont recalculées à partir des transactions : c'est une
          estimation.
        </p>
      </Section>

      <Section title="Valeur du portefeuille">
        <ValueHistory
          stamp={
            report.positions
              .map((p) => p.quote?.fetched_at ?? "")
              .sort()
              .at(-1) ?? report.last_import
          }
        />
      </Section>

      <Section title="Ordres manuels par trimestre">
        <QuarterChart quarters={quarters} current={current} />
      </Section>

      <Section title="Depuis l'ouverture">
        <dl className="grid gap-x-10 gap-y-5 sm:grid-cols-2 lg:grid-cols-4">
          <Fact label="Capital net apporté" value={euro(flows.capital_brought_in)} />
          <Fact
            label="Frais payés"
            value={euro(fees.total)}
            note={`${percent(fees.share_of_capital)} du capital apporté`}
          />
          <Fact
            label={`${plural(closed.count, "ligne soldée", "lignes soldées")}, résultat net`}
            value={signedEuro(closed.net)}
            note={`${closed.winners} gagnante${closed.winners > 1 ? "s" : ""} sur ${closed.count}`}
            loss={closed.net < 0}
          />
          <Fact label="Dividendes reçus" value={euro(flows.dividends)} />
        </dl>
      </Section>

      <p className="text-sm text-muted">
        {report.transactions} transactions, du {date(report.period?.from)} au{" "}
        {date(report.period?.to)}. Dernier import le {date(report.last_import)}.
      </p>
    </>
  );
}

function Fact({ label, value, note, loss }: { label: string; value: string; note?: string; loss?: boolean }) {
  return (
    <div className="border-t border-line pt-3">
      <dt className="text-sm text-muted">{label}</dt>
      <dd className={`num font-display text-2xl ${loss ? "text-loss" : ""}`}>{value}</dd>
      {note && <dd className="text-sm text-muted">{note}</dd>}
    </div>
  );
}

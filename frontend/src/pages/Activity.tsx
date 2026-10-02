import type { Report } from "../api";
import { PageTitle, Section, TableWrap } from "../components/ui";
import { accountName, euro, percent, quarterName } from "../format";

export function Activity({ report }: { report: Report }) {
  const { fees, flows } = report;
  const quarters = [...report.quarters].reverse();
  return (
    <>
      <PageTitle lead="Un ordre manuel est un achat ou une vente qui a payé des frais. Les exécutions du plan d'épargne et les arrondis sont gratuits et ne sont pas comptés.">
        {euro(fees.total)} de frais, soit {percent(fees.share_of_capital)} du capital apporté
      </PageTitle>

      <Section title="D'où viennent les frais">
        <TableWrap>
          <table className="data max-w-xl">
            <thead>
              <tr>
                <th>Poste</th>
                <th>Montant</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(fees.orders).map(([account, amount]) => (
                <tr key={account}>
                  <td>Frais d'ordre, {accountName(account)}</td>
                  <td className="num">{euro(amount)}</td>
                </tr>
              ))}
              <tr>
                <td>Frais de rechargement</td>
                <td className="num">{euro(fees.deposits)}</td>
              </tr>
              {fees.other !== 0 && (
                <tr>
                  <td>Autres frais</td>
                  <td className="num">{euro(fees.other)}</td>
                </tr>
              )}
            </tbody>
            <tfoot>
              <tr>
                <td>Total</td>
                <td className="num">{euro(fees.total)}</td>
              </tr>
            </tfoot>
          </table>
        </TableWrap>
      </Section>

      <Section title="Par trimestre">
        <TableWrap>
          <table className="data max-w-3xl">
            <thead>
              <tr>
                <th>Trimestre</th>
                <th>Ordres manuels</th>
                <th>Exécutions gratuites</th>
                <th>Frais d'ordre</th>
                <th>Frais de rechargement</th>
              </tr>
            </thead>
            <tbody>
              {quarters.map((q) => (
                <tr key={q.quarter}>
                  <td>{quarterName(q.quarter)}</td>
                  <td className="num">{q.manual_orders}</td>
                  <td className="num">{q.trades - q.manual_orders}</td>
                  <td className="num">{euro(q.order_fees)}</td>
                  <td className="num">{euro(q.deposit_fees)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      </Section>

      <Section
        title="Capital apporté"
        note="Le compte Trade Republic sert aussi de compte courant : les dépenses par carte sont retirées des versements pour obtenir ce qui a réellement été apporté au portefeuille."
      >
        <TableWrap>
          <table className="data max-w-xl">
            <tbody>
              <tr>
                <td>Versements (avant frais de rechargement)</td>
                <td className="num">{euro(flows.deposits)}</td>
              </tr>
              <tr>
                <td>Dépenses par carte</td>
                <td className="num">{euro(-flows.card_spending)}</td>
              </tr>
            </tbody>
            <tfoot>
              <tr>
                <td>Capital net apporté</td>
                <td className="num">{euro(flows.capital_brought_in)}</td>
              </tr>
            </tfoot>
          </table>
        </TableWrap>
      </Section>
    </>
  );
}

import type { Report } from "../api";
import { PageTitle, Result, TableWrap } from "../components/ui";
import { accountName, date, euro, plural, signedEuro, signedPercent } from "../format";

export function Closed({ report }: { report: Report }) {
  const s = report.closed_summary;
  if (s.count === 0) {
    return <PageTitle lead="Une ligne apparaît ici quand tous ses titres ont été vendus.">Aucune ligne soldée</PageTitle>;
  }
  return (
    <>
      <PageTitle
        lead={`${euro(s.bought)} engagés, ${signedEuro(s.gross)} avant frais, ${euro(s.fees)} de frais d'ordre. ${s.winners} gagnante${s.winners > 1 ? "s" : ""} sur ${s.count}.`}
      >
        {plural(s.count, "ligne soldée", "lignes soldées")} : {signedEuro(s.net)} net
      </PageTitle>
      <TableWrap>
        <table className="data">
          <thead>
            <tr>
              <th>Titre</th>
              <th>Compte</th>
              <th>Soldée le</th>
              <th>Durée</th>
              <th>Acheté</th>
              <th>Vendu</th>
              <th>Frais</th>
              <th>Résultat net</th>
            </tr>
          </thead>
          <tbody>
            {report.closed.map((c) => (
              <tr key={c.account + c.isin}>
                <td>
                  <a
                    className="underline decoration-line underline-offset-4 hover:decoration-accent"
                    href={`#/titre/${c.isin}`}
                  >
                    {c.name}
                  </a>
                </td>
                <td>{accountName(c.account)}</td>
                <td className="num">{date(c.closed_on)}</td>
                <td className="num">{c.holding_days != null ? `${c.holding_days} j` : "—"}</td>
                <td className="num">{euro(c.bought)}</td>
                <td className="num">{euro(c.sold)}</td>
                <td className="num">{euro(c.fees)}</td>
                <td>
                  <Result value={c.net}>
                    {signedEuro(c.net)} <span className="text-xs">({signedPercent(c.net_pct)})</span>
                  </Result>
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <td>Total</td>
              <td />
              <td />
              <td />
              <td className="num">{euro(s.bought)}</td>
              <td className="num">{euro(s.bought + s.gross)}</td>
              <td className="num">{euro(s.fees)}</td>
              <td>
                <Result value={s.net}>
                  {signedEuro(s.net)} <span className="text-xs">({signedPercent(s.net_pct)})</span>
                </Result>
              </td>
            </tr>
          </tfoot>
        </table>
      </TableWrap>
      <p className="mt-3 max-w-[75ch] text-sm text-muted">
        Résultat net = vendu − acheté − frais d'ordre. Les taxes sur transactions (
        {euro(s.taxes)} au total) et les dividendes reçus ne sont pas inclus.
      </p>
    </>
  );
}

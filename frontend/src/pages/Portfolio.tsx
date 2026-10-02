import { useState } from "react";
import { api, type Position, type Report } from "../api";
import { Notice, PageTitle, Result, Section, TableWrap } from "../components/ui";
import { accountName, date, euro, percent, quantity, signedEuro, signedPercent } from "../format";

export function Portfolio({ report, reload }: { report: Report; reload: () => void }) {
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

  return (
    <>
      <PageTitle lead="Le prix de revient est calculé au coût moyen : une vente libère le coût moyen des titres vendus, un fractionnement change la quantité sans changer le coût. Les cours se saisissent à la main pour l'instant ; la synchro Trade Republic les remplira.">
        Portefeuille
      </PageTitle>
      {error && (
        <div className="mb-6">
          <Notice tone="error">{error}</Notice>
        </div>
      )}
      {report.anomalies.length > 0 && (
        <div className="mb-6">
          <Notice tone="error">
            À vérifier dans l'export : {report.anomalies.join(" ; ")}
          </Notice>
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
                    <th>Coût moyen</th>
                    <th>Prix de revient</th>
                    <th>Cours</th>
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
                    <td />
                    <td className="num">{euro(account.open_cost)}</td>
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
  const stored = p.price != null ? String(p.price).replace(".", ",") : "";
  const [draft, setDraft] = useState(stored);
  const commit = () => {
    const value = draft.trim();
    if (value && value !== stored) save(p.isin, value);
    else setDraft(stored);
  };
  return (
    <tr>
      <td>
        {p.name}
        <span className="block text-xs text-muted">{p.isin}</span>
      </td>
      <td className="num">{quantity(p.shares)}</td>
      <td className="num">{euro(p.average_cost)}</td>
      <td className="num">{euro(p.cost)}</td>
      <td>
        <input
          aria-label={`Cours de ${p.name}`}
          title={p.price_date ? `Saisi le ${date(p.price_date)}` : "Aucun cours saisi"}
          inputMode="decimal"
          value={draft}
          placeholder="saisir"
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
          className="num w-24 rounded-md border border-line bg-surface px-2 py-1 text-right"
        />
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

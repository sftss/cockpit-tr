import { useEffect, useState } from "react";
import { api, type Gold, type GoldDraft, type GoldLot } from "../api";
import { accountTotal } from "../totals";
import type { Report } from "../api";
import { clock, date, euro, grams, signedEuro, signedPercent } from "../format";
import { Field, Notice, Quiet, Result, Section, TableWrap, inputClass } from "./ui";

const EMPTY: GoldDraft = { label: "", grams: "", cost: "", acquired_on: "", note: "" };

const draftOf = (lot: GoldLot): GoldDraft => ({
  label: lot.label,
  grams: String(lot.grams).replace(".", ","),
  cost: lot.cost == null ? "" : String(lot.cost).replace(".", ","),
  acquired_on: lot.acquired_on ?? "",
  note: lot.note ?? "",
});

/** Physical gold: kept apart from the broker portfolio, its weights and its rules. */
export function GoldSection({ report }: { report: Report }) {
  const [gold, setGold] = useState<Gold | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<number | "new" | null>(null);

  const load = () => api.gold().then(setGold).catch((e: Error) => setError(e.message));
  useEffect(() => {
    load().then(() =>
      api
        .refreshGoldPrice()
        .then(setGold)
        .catch(() => setError("Le cours de l'or n'a pas pu être relevé : le dernier cours connu est affiché.")),
    );
  }, []);

  const act = async (action: () => Promise<unknown>) => {
    try {
      setError(null);
      await action();
      setEditing(null);
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  if (!gold) return null;
  const broker = accountTotal(report);
  return (
    <Section
      title="Or physique"
      note="Compté à part : il n'entre ni dans les poids, ni dans les règles, ni dans la courbe de valeur. La valeur suit le cours mondial de l'or converti en euros ; la prime d'une pièce ou d'un lingot n'y est pas."
    >
      {error && (
        <div className="mb-4">
          <Notice tone="error">{error}</Notice>
        </div>
      )}
      {gold.lots.length > 0 && (
        <TableWrap>
          <table className="data max-w-4xl">
            <thead>
              <tr>
                <th>Lot</th>
                <th>Or fin</th>
                <th>Prix payé</th>
                <th>Valeur</th>
                <th>Résultat latent</th>
                <th>Modifier</th>
              </tr>
            </thead>
            <tbody>
              {gold.lots.map((lot) => (
                <tr key={lot.id}>
                  <td>
                    {lot.label}
                    {(lot.acquired_on || lot.note) && (
                      <span className="block text-xs text-muted">
                        {[lot.acquired_on && `acquis le ${date(lot.acquired_on)}`, lot.note]
                          .filter(Boolean)
                          .join(", ")}
                      </span>
                    )}
                  </td>
                  <td className="num">{grams(lot.grams)}</td>
                  <td className="num">{euro(lot.cost)}</td>
                  <td className="num">{euro(lot.value)}</td>
                  <td>
                    <Result value={lot.latent}>{signedEuro(lot.latent)}</Result>
                  </td>
                  <td>
                    <button
                      type="button"
                      onClick={() => setEditing(lot.id)}
                      aria-label={`Modifier le lot ${lot.label}`}
                      className="text-sm text-accent hover:underline"
                    >
                      Modifier
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td>Total</td>
                <td className="num">{grams(gold.grams)}</td>
                <td className="num">{euro(gold.cost)}</td>
                <td className="num">{euro(gold.value)}</td>
                <td>
                  <Result value={gold.latent}>
                    {signedEuro(gold.latent)}{" "}
                    {gold.latent_pct != null && (
                      <span className="text-xs">({signedPercent(gold.latent_pct)})</span>
                    )}
                  </Result>
                </td>
                <td />
              </tr>
            </tfoot>
          </table>
        </TableWrap>
      )}

      <p className="mt-3 max-w-[75ch] text-sm text-muted">
        {gold.eur_per_gram != null
          ? `Cours retenu : ${euro(gold.eur_per_gram)} le gramme, relevé le ${date(gold.fetched_at)} à ${clock(gold.fetched_at)}.`
          : "Aucun cours de l'or relevé pour l'instant."}
        {gold.value != null &&
          broker != null &&
          ` Portefeuille Trade Republic et or ensemble : ${euro(broker + gold.value)}.`}
      </p>

      <div className="mt-4">
        {editing === null ? (
          <Quiet onClick={() => setEditing("new")}>Ajouter un lot</Quiet>
        ) : (
          <LotForm
            key={editing}
            initial={editing === "new" ? EMPTY : draftOf(gold.lots.find((l) => l.id === editing)!)}
            save={(draft) =>
              act(() => (editing === "new" ? api.addGoldLot(draft) : api.updateGoldLot(editing, draft)))
            }
            cancel={() => setEditing(null)}
            remove={editing === "new" ? undefined : () => act(() => api.deleteGoldLot(editing))}
          />
        )}
      </div>
    </Section>
  );
}

function LotForm({
  initial,
  save,
  cancel,
  remove,
}: {
  initial: GoldDraft;
  save: (draft: GoldDraft) => void;
  cancel: () => void;
  remove?: () => void;
}) {
  const [draft, setDraft] = useState(initial);
  const set = (key: keyof GoldDraft) => (e: { target: { value: string } }) =>
    setDraft({ ...draft, [key]: e.target.value });
  const wide = `${inputClass} w-full`;
  return (
    <form
      aria-label="Lot d'or"
      className="max-w-4xl rounded-md border border-line bg-surface p-5"
      onSubmit={(e) => {
        e.preventDefault();
        save(draft);
      }}
    >
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Field label="Libellé" hint="Par exemple : pièces, lingotin.">
          <input required value={draft.label} onChange={set("label")} className={wide} />
        </Field>
        <Field label="Or fin, en grammes" hint="Le poids d'or pur, pas le poids brut de la pièce.">
          <input required inputMode="decimal" value={draft.grams} onChange={set("grams")} className={`${wide} num`} />
        </Field>
        <Field label="Prix payé, en euros" hint="Facultatif : sans lui, pas de résultat latent.">
          <input inputMode="decimal" value={draft.cost} onChange={set("cost")} className={`${wide} num`} />
        </Field>
        <Field label="Date d'acquisition">
          <input type="date" value={draft.acquired_on} onChange={set("acquired_on")} className={`${wide} num`} />
        </Field>
      </div>
      <div className="mt-4">
        <Field label="Note">
          <input value={draft.note} onChange={set("note")} className={wide} />
        </Field>
      </div>
      <div className="mt-5 flex flex-wrap items-center gap-3">
        <button
          type="submit"
          className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-surface hover:opacity-90"
        >
          Enregistrer le lot
        </button>
        <Quiet onClick={cancel}>Annuler</Quiet>
        {remove && (
          <button type="button" onClick={remove} className="ml-auto text-sm text-loss hover:underline">
            Supprimer le lot
          </button>
        )}
      </div>
    </form>
  );
}

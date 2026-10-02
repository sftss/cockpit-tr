import { useEffect, useState } from "react";
import { api, type Roadmap as RoadmapData, type RoadmapDraft, type RoadmapItem, type RoadmapStatus } from "../api";
import { HalalitudeLabel } from "../components/Halalitude";
import { Button, Field, Notice, PageTitle, Quiet, Section, inputClass } from "../components/ui";
import { accountName, clock, date, euro, plural } from "../format";

const EMPTY: RoadmapDraft = {
  name: "",
  isin: "",
  account: "",
  amount: "",
  entry_condition: "",
  entry_price: "",
  thesis: "",
  status: "idee",
  symbol: "",
};

const text = (value: number | null) => (value == null ? "" : String(value).replace(".", ","));

const draftOf = (item: RoadmapItem): RoadmapDraft => ({
  name: item.name,
  isin: item.isin ?? "",
  account: item.account ?? "",
  amount: text(item.amount),
  entry_condition: item.entry_condition ?? "",
  entry_price: text(item.entry_price),
  thesis: item.thesis ?? "",
  status: item.status,
  symbol: item.symbol ?? "",
});

export function Roadmap() {
  const [data, setData] = useState<RoadmapData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [editing, setEditing] = useState<number | "new" | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () =>
    api
      .roadmap()
      .then((result) => {
        setData(result);
        setError(null);
      })
      .catch((e: Error) => setError(e.message));

  const refreshPrices = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const outcome = await api.refreshRoadmapPrices();
      if (outcome.refused) setMessage("La source de cours a refusé la requête. Réessayer plus tard.");
      else if (outcome.unreachable) setMessage("La source de cours est injoignable.");
      else if (outcome.errors.length) setMessage(outcome.errors.join(" ; "));
      await load();
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    load().then(refreshPrices);
  }, []);

  const act = async (action: () => Promise<unknown>) => {
    try {
      await action();
      setEditing(null);
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  if (!data) return error ? <Notice tone="error">{error}</Notice> : null;
  const open = data.items.filter((i) => i.status === "idee" || i.status === "prevu");
  const closed = data.items.filter((i) => i.status === "execute" || i.status === "abandonne");
  const reached = open.filter((i) => i.reached).length;

  return (
    <>
      <PageTitle lead="Une cible n'est pas un ordre : elle dit quoi, à quelle condition et pourquoi. Le signal de cours ne fait rien d'autre que s'afficher, et aucun achat ne se fait sans vérification de la Halalitude.">
        Feuille de route :{" "}
        {open.length === 0 ? "aucune cible en cours" : plural(open.length, "cible en cours", "cibles en cours")}
        {reached > 0 && `, ${plural(reached, "cours d'entrée atteint", "cours d'entrée atteints")}`}
      </PageTitle>

      {error && (
        <div className="mb-6">
          <Notice tone="error">{error}</Notice>
        </div>
      )}
      {message && (
        <div className="mb-6">
          <Notice tone="error">{message}</Notice>
        </div>
      )}

      <div className="mb-10 flex flex-wrap items-center gap-3">
        <Button onClick={() => setEditing("new")} disabled={editing === "new"}>
          Ajouter une cible
        </Button>
        <Quiet onClick={refreshPrices} disabled={busy}>
          {busy ? "Actualisation…" : "Actualiser les cours"}
        </Quiet>
      </div>

      {editing === "new" && (
        <div className="mb-10">
          <ItemForm
            title="Nouvelle cible"
            initial={EMPTY}
            statuses={data.statuses}
            save={(draft) => act(() => api.addRoadmapItem(draft))}
            cancel={() => setEditing(null)}
          />
        </div>
      )}

      {open.length === 0 && editing !== "new" && (
        <p className="mb-12 max-w-[65ch] text-muted">
          La feuille de route est vide. Ajouter une cible, ou importer un fichier de réglages depuis
          la page Données.
        </p>
      )}

      <ItemList
        items={open}
        data={data}
        editing={editing}
        setEditing={setEditing}
        act={act}
      />

      {closed.length > 0 && (
        <Section title="Exécutées ou abandonnées">
          <ItemList items={closed} data={data} editing={editing} setEditing={setEditing} act={act} />
        </Section>
      )}
    </>
  );
}

function ItemList({
  items,
  data,
  editing,
  setEditing,
  act,
}: {
  items: RoadmapItem[];
  data: RoadmapData;
  editing: number | "new" | null;
  setEditing: (id: number | "new" | null) => void;
  act: (action: () => Promise<unknown>) => void;
}) {
  if (items.length === 0) return null;
  return (
    <ul className="mb-12 border-t border-line">
      {items.map((item) => (
        <li key={item.id} className="border-b border-line py-5">
          {editing === item.id ? (
            <ItemForm
              title={item.name}
              initial={draftOf(item)}
              statuses={data.statuses}
              save={(draft) => act(() => api.updateRoadmapItem(item.id, draft))}
              cancel={() => setEditing(null)}
              remove={() => act(() => api.deleteRoadmapItem(item.id))}
            />
          ) : (
            <Item item={item} status={data.statuses[item.status]} edit={() => setEditing(item.id)} />
          )}
        </li>
      ))}
    </ul>
  );
}

function Item({ item, status, edit }: { item: RoadmapItem; status: string; edit: () => void }) {
  return (
    <div className="grid gap-x-10 gap-y-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)_auto]">
      <div>
        <h3 className="font-display text-lg leading-snug">{item.name}</h3>
        <p className="text-sm text-muted">
          {[status, item.account && accountName(item.account), item.amount != null && euro(item.amount)]
            .filter(Boolean)
            .join(", ")}
        </p>
        {item.isin && (
          <p className="mt-1 text-xs">
            <span className="text-muted">{item.isin}</span>
            <span className="block">
              <HalalitudeLabel status={item.halalitude} />
            </span>
          </p>
        )}
      </div>
      <div className="max-w-[60ch] text-sm">
        {item.entry_condition && <p>{item.entry_condition}</p>}
        {item.thesis && <p className="mt-2 whitespace-pre-line text-muted">{item.thesis}</p>}
      </div>
      <div className="text-sm md:text-right">
        {item.entry_price != null && (
          <p className="num">
            <span className="text-muted">Entrée à </span>
            {euro(item.entry_price)}
          </p>
        )}
        {item.last_price != null ? (
          <p className="num">
            <span className="text-muted">Cours </span>
            {euro(item.last_price)}
            <span className="block text-xs text-muted">
              relevé le {date(item.last_price_at)} à {clock(item.last_price_at)}
            </span>
          </p>
        ) : (
          item.isin && <p className="text-xs text-muted">cours non relevé</p>
        )}
        {item.reached && <p className="mt-1 font-medium text-accent">Cours d'entrée atteint</p>}
        <button type="button" onClick={edit} className="mt-2 text-accent hover:underline">
          Modifier
        </button>
      </div>
    </div>
  );
}

function ItemForm({
  title,
  initial,
  statuses,
  save,
  cancel,
  remove,
}: {
  title: string;
  initial: RoadmapDraft;
  statuses: Record<RoadmapStatus, string>;
  save: (draft: RoadmapDraft) => void;
  cancel: () => void;
  remove?: () => void;
}) {
  const [draft, setDraft] = useState(initial);
  const set = (key: keyof RoadmapDraft) => (e: { target: { value: string } }) =>
    setDraft({ ...draft, [key]: e.target.value });
  const wide = `${inputClass} w-full`;
  return (
    <form
      aria-label={title}
      className="rounded-md border border-line bg-surface p-5"
      onSubmit={(e) => {
        e.preventDefault();
        save(draft);
      }}
    >
      <h3 className="font-display text-lg">{title}</h3>
      <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Field label="Titre visé">
          <input required value={draft.name} onChange={set("name")} className={wide} />
        </Field>
        <Field label="Code ISIN" hint="Pour la Halalitude et le cours.">
          <input value={draft.isin} onChange={set("isin")} className={wide} />
        </Field>
        <Field label="Compte">
          <select value={draft.account} onChange={set("account")} className={wide}>
            <option value="">Non décidé</option>
            <option value="CTO">Compte-titres</option>
            <option value="PEA">PEA</option>
          </select>
        </Field>
        <Field label="Statut">
          <select value={draft.status} onChange={set("status")} className={wide}>
            {Object.entries(statuses).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Montant prévu, en euros">
          <input inputMode="decimal" value={draft.amount} onChange={set("amount")} className={`${wide} num`} />
        </Field>
        <Field label="Cours d'entrée, en euros" hint="Signalé quand le cours passe à ce niveau ou en dessous.">
          <input
            inputMode="decimal"
            value={draft.entry_price}
            onChange={set("entry_price")}
            className={`${wide} num`}
          />
        </Field>
        <Field label="Symbole Yahoo" hint="Facultatif : cherché par ISIN s'il est vide.">
          <input value={draft.symbol} onChange={set("symbol")} className={wide} />
        </Field>
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Field label="Condition d'entrée">
          <textarea rows={3} value={draft.entry_condition} onChange={set("entry_condition")} className={wide} />
        </Field>
        <Field label="Thèse, en trois lignes">
          <textarea rows={3} value={draft.thesis} onChange={set("thesis")} className={wide} />
        </Field>
      </div>
      <div className="mt-5 flex flex-wrap items-center gap-3">
        <button
          type="submit"
          className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-surface hover:opacity-90"
        >
          Enregistrer la cible
        </button>
        <Quiet onClick={cancel}>Annuler</Quiet>
        {remove && (
          <button type="button" onClick={remove} className="ml-auto text-sm text-loss hover:underline">
            Supprimer la cible
          </button>
        )}
      </div>
    </form>
  );
}

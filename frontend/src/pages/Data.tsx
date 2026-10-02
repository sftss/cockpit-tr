import { useEffect, useRef, useState } from "react";
import {
  api,
  type ImportReport,
  type Instrument,
  type Report,
  type SnapshotSummary,
} from "../api";
import { Button, Notice, PageTitle, Section, TableWrap } from "../components/ui";
import { date, delayLabel } from "../format";

export function Data({ report, reload }: { report: Report | null; reload: () => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [result, setResult] = useState<ImportReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [snapshots, setSnapshots] = useState<SnapshotSummary[]>([]);
  const [label, setLabel] = useState("");
  const hasData = !!report && report.transactions > 0;

  const refreshSnapshots = () => api.snapshots().then(setSnapshots).catch(() => setSnapshots([]));
  useEffect(() => {
    refreshSnapshots();
  }, []);

  const importFile = async (file: File) => {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(await api.importCsv(await file.text()));
      reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  };

  const takeSnapshot = async () => {
    setError(null);
    try {
      await api.takeSnapshot(label.trim());
      setLabel("");
      refreshSnapshots();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <>
      <PageTitle
        lead={
          hasData
            ? "Réimporter un export plus récent n'ajoute que les nouvelles lignes : rien n'est modifié ni supprimé."
            : "Dans l'app Trade Republic, exporter les transactions au format CSV, puis choisir le fichier ici. Il reste sur cet ordinateur."
        }
      >
        {hasData ? "Données" : "Importer un export Trade Republic pour commencer"}
      </PageTitle>

      {error && (
        <div className="mb-6">
          <Notice tone="error">{error}</Notice>
        </div>
      )}

      <Section title="Import des transactions">
        <input
          ref={input}
          type="file"
          accept=".csv,text/csv"
          className="sr-only"
          aria-label="Fichier CSV de transactions"
          onChange={(e) => e.target.files?.[0] && importFile(e.target.files[0])}
        />
        <Button onClick={() => input.current?.click()} disabled={busy}>
          {busy ? "Import en cours…" : "Choisir le fichier CSV"}
        </Button>
        {result && (
          <div className="mt-4">
            <Notice>
              {result.total} lignes lues : {result.inserted} ajoutées, {result.already_present} déjà
              présentes
              {result.date_min && `, du ${date(result.date_min)} au ${date(result.date_max)}`}.
              {result.rejected.length > 0 && (
                <span className="block text-loss">
                  Lignes rejetées : {result.rejected.join(" ; ")}
                </span>
              )}
              {Object.keys(result.unknown_types).length > 0 && (
                <span className="block">
                  Types non reconnus, conservés mais ignorés dans les calculs :{" "}
                  {Object.entries(result.unknown_types)
                    .map(([type, count]) => `${type} (${count})`)
                    .join(", ")}
                </span>
              )}
            </Notice>
          </div>
        )}
      </Section>

      {hasData && <Quotes reload={reload} />}

      {hasData && (
        <Section
          title="Snapshots"
          note="Un snapshot fige les positions, les cours saisis et les totaux du jour. Il s'exporte en JSON (complet) ou en CSV (positions)."
        >
          <div className="flex flex-wrap items-center gap-3">
            <input
              aria-label="Nom du snapshot (facultatif)"
              placeholder="Nom (facultatif)"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              className="w-64 rounded-md border border-line bg-surface px-3 py-2 text-sm"
            />
            <Button onClick={takeSnapshot}>Créer un snapshot</Button>
          </div>
          {snapshots.length > 0 && (
            <div className="mt-6">
              <TableWrap>
                <table className="data max-w-2xl">
                  <thead>
                    <tr>
                      <th>Snapshot</th>
                      <th>Date</th>
                      <th>Lignes</th>
                      <th>Exporter</th>
                    </tr>
                  </thead>
                  <tbody>
                    {snapshots.map((s) => (
                      <tr key={s.id}>
                        <td>{s.label ?? `Snapshot ${s.id}`}</td>
                        <td className="num">{date(s.taken_at)}</td>
                        <td className="num">{s.positions}</td>
                        <td>
                          <a className="text-accent underline" href={`/api/snapshots/${s.id}/export.json`}>
                            JSON
                          </a>
                          {" · "}
                          <a className="text-accent underline" href={`/api/snapshots/${s.id}/export.csv`}>
                            CSV
                          </a>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableWrap>
            </div>
          )}
        </Section>
      )}
    </>
  );
}

/** Where each instrument is quoted, with a way to correct the symbol by hand. */
function Quotes({ reload }: { reload: () => void }) {
  const [items, setItems] = useState<Instrument[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const fetchItems = () => api.instruments().then(setItems).catch(() => setItems([]));
  useEffect(() => {
    fetchItems();
  }, []);

  const run = async (label: string, call: () => Promise<{ errors: string[]; refused: boolean; unreachable: boolean }>) => {
    setBusy(label);
    setMessage(null);
    try {
      const outcome = await call();
      if (outcome.refused) setMessage("La source de cours a refusé la requête. Réessayer plus tard.");
      else if (outcome.unreachable) setMessage("La source de cours est injoignable.");
      else if (outcome.errors.length) setMessage(outcome.errors.join(" ; "));
      await fetchItems();
      reload();
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const saveSymbol = async (isin: string, symbol: string) => {
    await api.setSymbol(isin, symbol);
    await run("cours", api.refreshQuotes);
  };

  const held = items.filter((i) => i.held);
  const others = items.filter((i) => !i.held);

  return (
    <Section
      title="Cours"
      note="Les cours viennent de Yahoo Finance, recherchés par code ISIN : une source gratuite et non officielle, qui peut refuser ou changer. Si un titre n'est pas trouvé, ou pas sur la bonne place, saisir son symbole Yahoo (par exemple AI.PA). Un symbole vide relance la recherche par ISIN."
    >
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <Button onClick={() => run("cours", api.refreshQuotes)} disabled={busy !== null}>
          {busy === "cours" ? "Actualisation…" : "Actualiser les cours"}
        </Button>
        <Button onClick={() => run("historique", api.loadHistory)} disabled={busy !== null}>
          {busy === "historique" ? "Chargement, une minute environ…" : "Charger l'historique des cours"}
        </Button>
      </div>
      {message && (
        <div className="mb-5">
          <Notice tone="error">{message}</Notice>
        </div>
      )}
      <TableWrap>
        <table className="data max-w-4xl">
          <thead>
            <tr>
              <th>Titre</th>
              <th>Symbole</th>
              <th>Devise</th>
              <th>Fraîcheur</th>
              <th>Jours de cours</th>
            </tr>
          </thead>
          <tbody>
            {[...held, ...others].map((item) => (
              <tr key={item.isin}>
                <td>
                  {item.name}
                  <span className="block text-xs text-muted">
                    {item.isin}
                    {!item.held && ", ligne soldée"}
                  </span>
                </td>
                <td>
                  <SymbolInput item={item} save={saveSymbol} />
                </td>
                <td>{item.currency ?? "—"}</td>
                <td>
                  {item.status === "introuvable"
                    ? "non trouvé"
                    : item.symbol
                      ? delayLabel(item.delay_minutes)
                      : "pas encore recherché"}
                </td>
                <td className="num">{item.price_days}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableWrap>
    </Section>
  );
}

function SymbolInput({ item, save }: { item: Instrument; save: (isin: string, symbol: string) => void }) {
  const stored = item.symbol ?? "";
  const [draft, setDraft] = useState(stored);
  useEffect(() => setDraft(stored), [stored]);
  return (
    <input
      aria-label={`Symbole Yahoo de ${item.name}`}
      value={draft}
      placeholder="symbole"
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => draft.trim() !== stored && save(item.isin, draft.trim())}
      onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
      className="w-28 rounded-md border border-line bg-surface px-2 py-1 text-right"
    />
  );
}

import { useEffect, useRef, useState } from "react";
import { api, type ImportReport, type Report, type SnapshotSummary } from "../api";
import { Button, Notice, PageTitle, Section, TableWrap } from "../components/ui";
import { date } from "../format";

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

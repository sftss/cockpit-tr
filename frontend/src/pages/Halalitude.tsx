import { useEffect, useState } from "react";
import { api, type Compliance as ComplianceData, type ComplianceItem, type HalalitudeStatus } from "../api";
import { HalalitudeLabel } from "../components/Halalitude";
import { Notice, PageTitle, Quiet, Section, TableWrap, inputClass } from "../components/ui";
import { plural, today } from "../format";

const GROUPS = [
  { id: "detenu", title: "Lignes détenues" },
  { id: "cible", title: "Cibles de la feuille de route" },
  { id: "autre", title: "Autres titres vérifiés" },
] as const;

export function HalalitudePage({ reload }: { reload: () => void }) {
  const [data, setData] = useState<ComplianceData | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () =>
    api
      .compliance()
      .then((result) => {
        setData(result);
        setError(null);
      })
      .catch((e: Error) => setError(e.message));
  useEffect(() => {
    load();
  }, []);

  const save = async (entry: { isin: string; status: string; checked_on: string; note: string }) => {
    try {
      await api.recordCompliance(entry);
      await load();
      reload();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  if (!data) return error ? <Notice tone="error">{error}</Notice> : null;
  const { missing, stale, not_compliant: flagged } = data.summary;
  const headline =
    missing + stale === 0
      ? "tous les statuts sont à jour"
      : [
          stale > 0 && plural(stale, "statut à revérifier", "statuts à revérifier"),
          missing > 0 && plural(missing, "non renseigné", "non renseignés"),
        ]
          .filter(Boolean)
          .join(", ");

  return (
    <>
      <PageTitle
        lead={`L'application ne vérifie rien elle-même : elle garde le statut relevé dans les screeners et la date de ce relevé. Au-delà de ${data.validity_days} jours, le statut est à revérifier.`}
      >
        Halalitude : {headline}
      </PageTitle>

      {error && (
        <div className="mb-6">
          <Notice tone="error">{error}</Notice>
        </div>
      )}
      {flagged > 0 && (
        <div className="mb-8">
          <Notice>
            {plural(flagged, "ligne détenue n'est pas notée", "lignes détenues ne sont pas notées")}{" "}
            « halal ».
          </Notice>
        </div>
      )}

      {GROUPS.map((group) => {
        const items = data.items.filter((item) => item.group === group.id);
        if (items.length === 0) return null;
        return (
          <Section key={group.id} title={group.title}>
            <TableWrap>
              <table className="data compliance">
                <thead>
                  <tr>
                    <th>Titre</th>
                    <th>Statut relevé</th>
                    <th>Relevé le</th>
                    <th>Note</th>
                    <th>Enregistrer</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <Row key={item.isin} item={item} statuses={data.statuses} save={save} />
                  ))}
                </tbody>
              </table>
            </TableWrap>
          </Section>
        );
      })}

      <AddOther statuses={data.statuses} save={save} />
    </>
  );
}

function Row({
  item,
  statuses,
  save,
}: {
  item: ComplianceItem;
  statuses: Record<HalalitudeStatus, string>;
  save: (entry: { isin: string; status: string; checked_on: string; note: string }) => void;
}) {
  const [status, setStatus] = useState<string>(item.status ?? "");
  const [day, setDay] = useState(today());
  const [note, setNote] = useState(item.note ?? "");
  useEffect(() => {
    setStatus(item.status ?? "");
    setNote(item.note ?? "");
  }, [item.status, item.note, item.checked_on]);

  return (
    <tr>
      <td>
        {item.name}
        <span className="block text-xs text-muted">{item.isin}</span>
        <span className="block text-xs">
          <HalalitudeLabel status={item} />
        </span>
      </td>
      <td>
        <select
          aria-label={`Halalitude de ${item.name}`}
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className={inputClass}
        >
          <option value="">à choisir</option>
          {Object.entries(statuses).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </td>
      <td>
        <input
          aria-label={`Date du relevé pour ${item.name}`}
          type="date"
          value={day}
          max={today()}
          onChange={(e) => setDay(e.target.value)}
          className={`${inputClass} num`}
        />
      </td>
      <td>
        <input
          aria-label={`Note sur ${item.name}`}
          placeholder="Screeners consultés, remarque"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          className={`${inputClass} w-full text-left`}
        />
      </td>
      <td>
        <Quiet
          onClick={() => save({ isin: item.isin, status, checked_on: day, note })}
          disabled={!status}
        >
          Enregistrer
        </Quiet>
      </td>
    </tr>
  );
}

/** A status for an instrument that is neither held nor on the roadmap yet. */
function AddOther({
  statuses,
  save,
}: {
  statuses: Record<HalalitudeStatus, string>;
  save: (entry: { isin: string; status: string; checked_on: string; note: string }) => void;
}) {
  const [isin, setIsin] = useState("");
  const [status, setStatus] = useState("");
  const submit = () => {
    save({ isin: isin.trim(), status, checked_on: today(), note: "" });
    setIsin("");
    setStatus("");
  };
  return (
    <Section
      title="Vérifier un autre titre"
      note="Pour un titre regardé dans les screeners avant de l'inscrire sur la feuille de route."
    >
      <div className="flex flex-wrap items-center gap-3">
        <input
          aria-label="Code ISIN du titre"
          placeholder="Code ISIN"
          value={isin}
          onChange={(e) => setIsin(e.target.value)}
          className={`${inputClass} w-44`}
        />
        <select
          aria-label="Statut relevé"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className={inputClass}
        >
          <option value="">Statut à choisir</option>
          {Object.entries(statuses).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <Quiet onClick={submit} disabled={!isin.trim() || !status}>
          Enregistrer
        </Quiet>
      </div>
    </Section>
  );
}

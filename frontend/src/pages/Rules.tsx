import { useEffect, useState } from "react";
import { api, type Deviation, type Rule, type RuleKind, type RuleLine, type RulesState } from "../api";
import { Notice, PageTitle, Quiet, Section, TableWrap, inputClass } from "../components/ui";
import { accountName, date, euro, number, percent, plural, quarterName, today } from "../format";

const OPERATIONS: Record<string, string> = {
  BUY: "Achat",
  SELL: "Vente",
  CUSTOMER_INPAYMENT: "Rechargement",
  TRANSFER_INBOUND: "Versement",
};

const amountOf = (unit: string, value: number) =>
  unit === "€" ? euro(value) : unit === "%" ? `${number(value)} %` : number(value);

export function Rules() {
  const [state, setState] = useState<RulesState | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () =>
    api
      .rules()
      .then((data) => {
        setState(data);
        setError(null);
      })
      .catch((e: Error) => setError(e.message));
  useEffect(() => {
    load();
  }, []);

  const act = async (action: () => Promise<unknown>) => {
    try {
      await action();
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  if (!state) return error ? <Notice tone="error">{error}</Notice> : null;

  const orders = state.current.find((line) => line.kind === "ordres_manuels_trimestre")!;
  return (
    <>
      <PageTitle
        lead={
          !state.has_rules
            ? "Aucune règle n'a encore de valeur : les compteurs s'affichent, mais rien n'est signalé. Donner une valeur aux règles plus bas, ou importer un fichier de réglages depuis la page Données."
            : state.pending > 0
              ? `${plural(state.pending, "écart attend", "écarts attendent")} un motif. Une règle ne bloque rien : elle demande d'écrire pourquoi on s'en écarte.`
              : "Aucun écart sans motif. Une règle ne bloque rien : elle demande d'écrire pourquoi on s'en écarte."
        }
      >
        {quarterName(state.quarter)} : {plural(orders.count, "ordre manuel", "ordres manuels")}
        {orders.limit != null && ` sur ${number(orders.limit)} prévus`}
      </PageTitle>

      {error && (
        <div className="mb-6">
          <Notice tone="error">{error}</Notice>
        </div>
      )}

      <Section title="Ce trimestre">
        <Counters lines={state.current} />
      </Section>

      <Section
        title="Écarts"
        note="Les transactions importées qui s'écartent d'une règle en vigueur le jour où elles ont été passées. Le motif s'enregistre en quittant le champ."
      >
        {state.deviations.length === 0 ? (
          <p className="text-muted">Aucune transaction ne s'écarte des règles en vigueur.</p>
        ) : (
          <TableWrap>
            <table className="data deviations">
              <thead>
                <tr>
                  <th>Opération</th>
                  <th>Montant</th>
                  <th>Écart</th>
                  <th>Motif</th>
                </tr>
              </thead>
              <tbody>
                {state.deviations.map((d) => (
                  <DeviationRow
                    key={d.transaction_id}
                    deviation={d}
                    save={(reason) => act(() => api.setReason(d.transaction_id, reason))}
                  />
                ))}
              </tbody>
            </table>
          </TableWrap>
        )}
      </Section>

      <Section
        title="Valeurs des règles"
        note="Une nouvelle valeur s'applique à partir de sa date d'effet ; l'ancienne reste dans l'historique et continue de valoir pour les transactions passées. Ces valeurs restent sur cet ordinateur."
      >
        <TableWrap>
          <table className="data rules">
            <thead>
              <tr>
                <th>Règle</th>
                <th>En vigueur</th>
                <th>Nouvelle valeur</th>
              </tr>
            </thead>
            <tbody>
              {state.kinds.map((kind) => (
                <RuleRow
                  key={kind.kind}
                  kind={kind}
                  rules={state.rules.filter((r) => r.kind === kind.kind)}
                  save={(rule) => act(() => api.setRule(rule))}
                />
              ))}
            </tbody>
          </table>
        </TableWrap>
        <History state={state} remove={(id) => act(() => api.deleteRule(id))} />
      </Section>
    </>
  );
}

export function Counters({ lines }: { lines: RuleLine[] }) {
  return (
    <TableWrap>
      <table className="data counters">
        <thead>
          <tr>
            <th>Règle</th>
            <th>Constaté</th>
            <th>Prévu</th>
            <th>État</th>
          </tr>
        </thead>
        <tbody>
          {lines.map((line) => (
            <tr key={line.kind}>
              <td>{line.label}</td>
              <td className="num">{observed(line)}</td>
              <td className="tabular-nums">{expected(line)}</td>
              <td>
                {line.breaches > 0 ? (
                  <span className="text-alert">{plural(line.breaches, "écart", "écarts")}</span>
                ) : hasValue(line) ? (
                  "dans la règle"
                ) : (
                  <span className="text-muted">pas de valeur</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </TableWrap>
  );
}

const hasValue = (line: RuleLine) =>
  line.kind === "achat_minimum" ? (line.minimums?.length ?? 0) > 0 : line.limit != null;

function observed(line: RuleLine): string {
  switch (line.kind) {
    case "nouvelle_ligne_valeur_minimum":
      return plural(line.count, "nouvelle ligne", "nouvelles lignes");
    case "achat_minimum":
      return plural(line.count, "achat sous le minimum", "achats sous le minimum");
    case "poids_maximum":
      return line.lines?.length
        ? line.lines.map((l) => `${l.name} ${percent(l.weight)}`).join(", ")
        : "aucune ligne au-dessus";
    default:
      return amountOf(line.unit, line.count);
  }
}

function expected(line: RuleLine): string {
  if (line.kind === "achat_minimum") {
    return line.minimums?.length
      ? line.minimums
          .map((m) => `au moins ${euro(m.value)}${m.account ? ` (${accountName(m.account)})` : ""}`)
          .join(", ")
      : "—";
  }
  if (line.limit == null) return "—";
  if (line.kind === "nouvelle_ligne_valeur_minimum") {
    const worth = line.portfolio_value != null ? ` ; il vaut ${euro(line.portfolio_value)}` : "";
    return `aucune tant que le portefeuille vaut moins de ${euro(line.limit)}${worth}`;
  }
  return `au plus ${amountOf(line.unit, line.limit)}`;
}

function DeviationRow({ deviation: d, save }: { deviation: Deviation; save: (reason: string) => void }) {
  const stored = d.reason ?? "";
  const [draft, setDraft] = useState(stored);
  useEffect(() => setDraft(stored), [stored]);
  return (
    <tr>
      <td>
        {OPERATIONS[d.type] ?? d.type}
        {d.name && `, ${d.name}`}
        <span className="block text-xs text-muted">
          {date(d.date)}, {accountName(d.account)}
        </span>
      </td>
      <td className="num">{euro(d.amount)}</td>
      <td>
        <ul>
          {d.breaches.map((b) => (
            <li key={b.kind}>{b.detail}</li>
          ))}
        </ul>
      </td>
      <td>
        <textarea
          aria-label={`Motif de l'écart du ${date(d.date)}${d.name ? `, ${d.name}` : ""}`}
          rows={2}
          value={draft}
          placeholder="Pourquoi cet écart ?"
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => draft.trim() !== stored && save(draft)}
          className={`${inputClass} w-full text-left ${stored ? "" : "border-alert"}`}
        />
      </td>
    </tr>
  );
}

const inForce = (rule: Rule, day: string) =>
  rule.valid_from <= day && (rule.valid_to == null || rule.valid_to >= day);

function RuleRow({
  kind,
  rules,
  save,
}: {
  kind: RuleKind;
  rules: Rule[];
  save: (rule: { kind: string; value: string; valid_from: string; account: string | null }) => void;
}) {
  const day = today();
  const current = rules.filter((r) => inForce(r, day));
  const [value, setValue] = useState("");
  const [from, setFrom] = useState(day);
  const [account, setAccount] = useState("");
  const submit = () => {
    if (!value.trim()) return;
    save({ kind: kind.kind, value: value.trim(), valid_from: from, account: account || null });
    setValue("");
  };
  return (
    <tr>
      <td>
        {kind.label}
        <span className="block max-w-[52ch] text-xs text-muted">{kind.help}</span>
      </td>
      <td>
        {current.length === 0 ? (
          <span className="text-muted">pas de valeur</span>
        ) : (
          current.map((r) => (
            <span key={r.id} className="num block">
              {amountOf(kind.unit, r.value)}
              {r.account && `, ${accountName(r.account)}`}
              <span className="block text-xs text-muted">depuis le {date(r.valid_from)}</span>
            </span>
          ))
        )}
      </td>
      <td>
        <span className="flex flex-wrap items-center justify-end gap-2">
          {kind.per_account && (
            <select
              aria-label={`Compte, ${kind.label}`}
              value={account}
              onChange={(e) => setAccount(e.target.value)}
              className={inputClass}
            >
              <option value="">Tous les comptes</option>
              <option value="CTO">Compte-titres</option>
              <option value="PEA">PEA</option>
            </select>
          )}
          <input
            aria-label={`Nouvelle valeur, ${kind.label} (${kind.unit})`}
            inputMode="decimal"
            value={value}
            placeholder={kind.unit === "€" || kind.unit === "%" ? kind.unit : "nombre"}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
            className={`${inputClass} num w-24 text-right`}
          />
          <input
            aria-label={`Date d'effet, ${kind.label}`}
            type="date"
            value={from}
            onChange={(e) => setFrom(e.target.value)}
            className={`${inputClass} num`}
          />
          <Quiet onClick={submit} disabled={!value.trim()}>
            Enregistrer
          </Quiet>
        </span>
      </td>
    </tr>
  );
}

function History({ state, remove }: { state: RulesState; remove: (id: number) => void }) {
  if (state.rules.length === 0) return null;
  const labels = Object.fromEntries(state.kinds.map((k) => [k.kind, k]));
  const rows = [...state.rules].sort((a, b) => b.valid_from.localeCompare(a.valid_from));
  return (
    <details className="mt-6">
      <summary className="cursor-pointer text-sm text-accent">
        Historique des valeurs ({state.rules.length})
      </summary>
      <div className="mt-3">
        <TableWrap>
          <table className="data max-w-3xl">
            <thead>
              <tr>
                <th>Règle</th>
                <th>Valeur</th>
                <th>Du</th>
                <th>Au</th>
                <th>Retirer</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td>
                    {labels[r.kind].label}
                    {r.account && `, ${accountName(r.account)}`}
                  </td>
                  <td className="num">{amountOf(labels[r.kind].unit, r.value)}</td>
                  <td className="num">{date(r.valid_from)}</td>
                  <td className="num">{r.valid_to ? date(r.valid_to) : "en vigueur"}</td>
                  <td>
                    <button
                      type="button"
                      onClick={() => remove(r.id)}
                      aria-label={`Supprimer la valeur du ${date(r.valid_from)}, ${labels[r.kind].label}`}
                      className="text-sm text-accent hover:underline"
                    >
                      Supprimer
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      </div>
    </details>
  );
}

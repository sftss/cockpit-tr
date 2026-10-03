import { useEffect, useRef, useState } from "react";
import {
  api,
  type ControlState,
  type Report,
  type Roadmap,
  type Ticket,
  type TicketDraft,
  type TicketListing,
  type TicketOrderType,
  type TicketSide,
  type TicketTrade,
} from "../api";
import { Button, Field, Notice, PageTitle, Quiet, Section, TableWrap, inputClass } from "../components/ui";
import { accountName, clock, date, euro, percent, plural, quantity } from "../format";

const OTHER = "autre";

/** What a control concluded, in words: the colour only repeats it. */
const OUTCOME: Record<ControlState, string> = {
  ok: "Passe",
  bloquant: "Arrête le ticket",
  motif: "Motif demandé",
  avertissement: "À regarder",
  info: "Information",
  attente: "À compléter",
  erreur: "À corriger",
};

const text = (value: number | null) => (value == null ? "" : String(value).replace(".", ","));

const decimal = (value: string) => {
  const parsed = Number(value.replace(/\s/g, "").replace(",", "."));
  return value.trim() !== "" && Number.isFinite(parsed) ? parsed : null;
};

export function Tickets({ report }: { report: Report }) {
  const [data, setData] = useState<TicketListing | null>(null);
  const [roadmap, setRoadmap] = useState<Roadmap | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () =>
    api
      .tickets()
      .then(setData)
      .catch((e: Error) => setError(e.message));

  useEffect(() => {
    load();
    api.roadmap().then(setRoadmap).catch(() => setRoadmap(null));
  }, [report.last_import]);

  /** Run one action, then show the tickets as they now stand. */
  const act = async (action: () => Promise<unknown>) => {
    try {
      await action();
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
    await load();
  };

  if (!data) return error ? <Notice tone="error">{error}</Notice> : null;
  const ready = data.tickets.filter((t) => t.status === "pret");
  const drafts = data.tickets.filter((t) => t.status === "brouillon");
  const executed = data.tickets.filter((t) => t.status === "execute");
  const dropped = data.tickets.filter((t) => t.status === "abandonne");
  const counts = [
    ready.length > 0 && plural(ready.length, "prêt", "prêts"),
    drafts.length > 0 && plural(drafts.length, "brouillon", "brouillons"),
  ].filter(Boolean);

  return (
    <>
      <PageTitle lead="Un ticket prépare et contrôle un ordre. L'ordre se passe ensuite dans l'application Trade Republic, à la main : rien ne part de cet ordinateur.">
        Tickets : {counts.length > 0 ? counts.join(", ") : "aucun ticket en cours"}
      </PageTitle>

      {error && (
        <div className="mb-6">
          <Notice tone="error">{error}</Notice>
        </div>
      )}

      <Section title="Nouveau ticket">
        <NewTicket report={report} roadmap={roadmap} create={(draft) => act(() => api.createTicket(draft))} />
      </Section>

      {ready.length > 0 && (
        <Section
          title="Prêts"
          note="À recopier dans Trade Republic. Après l'ordre, importer le nouvel export des transactions : le ticket se rapproche de sa transaction."
        >
          <ul className="border-t border-line">
            {ready.map((ticket) => (
              <li key={ticket.id} className="border-b border-line py-6">
                <ReadyTicket ticket={ticket} data={data} act={act} />
              </li>
            ))}
          </ul>
        </Section>
      )}

      {drafts.length > 0 && (
        <Section title="Brouillons">
          <ul className="border-t border-line">
            {drafts.map((ticket) => (
              <li key={ticket.id} className="border-b border-line py-6">
                <DraftTicket ticket={ticket} data={data} act={act} />
              </li>
            ))}
          </ul>
        </Section>
      )}

      {executed.length > 0 && (
        <Section title="Exécutés" note="Ce qui était prévu, à côté de ce qui a été fait.">
          <Executed tickets={executed} data={data} act={act} />
        </Section>
      )}

      {dropped.length > 0 && (
        <Section title="Abandonnés">
          <ul className="border-t border-line text-sm">
            {dropped.map((ticket) => (
              <li key={ticket.id} className="flex flex-wrap items-baseline gap-x-4 gap-y-1 border-b border-line py-3">
                <span>
                  {data.sides[ticket.side]} · {ticket.name}, {accountName(ticket.account)}
                  {ticket.amount != null && `, ${euro(ticket.amount)}`}
                </span>
                <span className="text-muted">abandonné le {date(ticket.closed_at)}</span>
                <span className="ml-auto flex gap-4">
                  <LinkButton onClick={() => act(() => api.setTicketStatus(ticket.id, "brouillon"))}>
                    Reprendre
                  </LinkButton>
                  <LinkButton tone="loss" onClick={() => act(() => api.deleteTicket(ticket.id))}>
                    Supprimer
                  </LinkButton>
                </span>
              </li>
            ))}
          </ul>
        </Section>
      )}
    </>
  );
}

function LinkButton({
  children,
  onClick,
  tone,
}: {
  children: string;
  onClick: () => void;
  tone?: "loss";
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`text-sm hover:underline ${tone === "loss" ? "text-loss" : "text-accent"}`}
    >
      {children}
    </button>
  );
}

/** Pick a title among what is held and what is planned, or type another ISIN. */
function NewTicket({
  report,
  roadmap,
  create,
}: {
  report: Report;
  roadmap: Roadmap | null;
  create: (draft: TicketDraft) => void;
}) {
  const held = [...new Map(report.positions.map((p) => [p.isin, p.name])).entries()].sort((a, b) =>
    a[1].localeCompare(b[1], "fr"),
  );
  const targets = (roadmap?.items ?? []).filter(
    (item) => item.isin && (item.status === "idee" || item.status === "prevu"),
  );
  const [choice, setChoice] = useState("");
  const [isin, setIsin] = useState("");
  const [name, setName] = useState("");
  const [side, setSide] = useState<TicketSide>("BUY");
  const [account, setAccount] = useState("CTO");

  const target = choice.startsWith("cible:") ? targets.find((t) => `cible:${t.id}` === choice) : null;
  const chosenIsin = choice === OTHER ? isin.trim().toUpperCase() : (target?.isin ?? choice);
  const accountsHolding = report.positions.filter((p) => p.isin === chosenIsin).map((p) => p.account);

  const choose = (value: string) => {
    setChoice(value);
    const picked = value.startsWith("cible:") ? targets.find((t) => `cible:${t.id}` === value) : null;
    const holding = report.positions.filter((p) => p.isin === (picked?.isin ?? value));
    if (picked?.account) setAccount(picked.account);
    else if (holding.length > 0) setAccount(holding[0].account);
    if (holding.length === 0) setSide("BUY");
  };

  const wide = `${inputClass} w-full`;
  return (
    <form
      aria-label="Nouveau ticket"
      className="grid max-w-[60rem] items-end gap-4 sm:grid-cols-2 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)_auto]"
      onSubmit={(e) => {
        e.preventDefault();
        create({
          isin: chosenIsin,
          side,
          account,
          ...(choice === OTHER && name.trim() ? { name: name.trim() } : {}),
          ...(target ? { roadmap_item_id: target.id } : {}),
        });
      }}
    >
      <Field label="Titre">
        <select required value={choice} onChange={(e) => choose(e.target.value)} className={wide}>
          <option value="">Choisir un titre</option>
          {held.length > 0 && (
            <optgroup label="Lignes détenues">
              {held.map(([code, label]) => (
                <option key={code} value={code}>
                  {label}
                </option>
              ))}
            </optgroup>
          )}
          {targets.length > 0 && (
            <optgroup label="Cibles de la feuille de route">
              {targets.map((item) => (
                <option key={item.id} value={`cible:${item.id}`}>
                  {item.name}
                </option>
              ))}
            </optgroup>
          )}
          <option value={OTHER}>Autre titre, par son code ISIN</option>
        </select>
      </Field>
      <Field label="Sens">
        <select value={side} onChange={(e) => setSide(e.target.value as TicketSide)} className={wide}>
          <option value="BUY">Achat</option>
          <option value="SELL" disabled={accountsHolding.length === 0}>
            Vente
          </option>
        </select>
      </Field>
      <Field label="Compte">
        <select value={account} onChange={(e) => setAccount(e.target.value)} className={wide}>
          <option value="CTO">Compte-titres</option>
          <option value="PEA">PEA</option>
        </select>
      </Field>
      <button
        type="submit"
        className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-surface hover:opacity-90"
      >
        Créer le brouillon
      </button>
      {choice === OTHER && (
        <>
          <Field label="Code ISIN" hint="12 caractères, par exemple FR0000120404.">
            <input required value={isin} onChange={(e) => setIsin(e.target.value)} className={wide} />
          </Field>
          <Field label="Nom du titre">
            <input value={name} onChange={(e) => setName(e.target.value)} className={wide} />
          </Field>
        </>
      )}
    </form>
  );
}

function Heading({ ticket, data }: { ticket: Ticket; data: TicketListing }) {
  return (
    <div>
      <h3 className="font-display text-lg leading-snug">
        {data.sides[ticket.side]} · {ticket.name}
      </h3>
      <p className="text-sm text-muted">
        {[accountName(ticket.account), ticket.isin, ticket.instrument].filter(Boolean).join(", ")}
        {ticket.held > 0 && `. Détenu sur ce compte : ${quantity(ticket.held)}`}
      </p>
      {ticket.proposed_by === "assistant" && (
        <p className="text-xs text-accent">brouillon préparé par l'assistant, à la demande</p>
      )}
      {ticket.target && (
        <p className="mt-2 max-w-[70ch] text-sm">
          <span className="text-muted">Cible de la feuille de route : </span>
          {ticket.target.name}
          {ticket.target.thesis && (
            <span className="mt-1 block whitespace-pre-line text-muted">{ticket.target.thesis}</span>
          )}
        </p>
      )}
    </div>
  );
}

function Controls({ ticket }: { ticket: Ticket }) {
  if (ticket.controls.length === 0) return null;
  const tone = (state: ControlState) =>
    state === "bloquant"
      ? "font-medium text-alert"
      : state === "ok" || state === "info"
        ? "text-muted"
        : "text-alert";
  // Three columns on a wide screen; on a narrow one each control stacks, so the
  // detail, which is a sentence, never hides behind a sideways scroll.
  const columns = "md:grid md:grid-cols-[minmax(0,15rem)_9.5rem_minmax(0,1fr)] md:gap-x-6";
  return (
    <div className="max-w-[60rem]">
      <p className="text-sm font-medium">Contrôles</p>
      <div className={`mt-2 hidden border-b border-line pb-2 text-[13px] font-medium text-muted ${columns}`} aria-hidden="true">
        <span>Contrôle</span>
        <span>Résultat</span>
        <span>Détail</span>
      </div>
      <ul className="border-t border-line md:border-t-0">
        {ticket.controls.map((control) => (
          <li key={control.key} className={`border-b border-line py-2 ${columns}`}>
            <span className="block">{control.label}</span>
            <span className={`block ${tone(control.state)}`}>{OUTCOME[control.state]}</span>
            <span className="block text-sm md:text-[15px]">{control.detail}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

type Fields = {
  shares: string;
  amount: string;
  order_type: TicketOrderType;
  limit_price: string;
  price: string;
  fee: string;
  reason: string;
};

const fieldsOf = (ticket: Ticket): Fields => ({
  shares: text(ticket.shares),
  amount: "",
  order_type: ticket.order_type,
  limit_price: text(ticket.limit_price),
  price: text(ticket.price),
  fee: text(ticket.fee),
  reason: ticket.reason ?? "",
});

function DraftTicket({
  ticket,
  data,
  act,
}: {
  ticket: Ticket;
  data: TicketListing;
  act: (action: () => Promise<unknown>) => Promise<void>;
}) {
  const saved = fieldsOf(ticket);
  const [draft, setDraft] = useState(saved);
  const [busy, setBusy] = useState(false);
  // What was saved changed (a reload, a price asked again): start again from it.
  const stamp = JSON.stringify(saved);
  useEffect(() => setDraft(JSON.parse(stamp) as Fields), [stamp]);
  const latest = useRef(stamp);
  latest.current = stamp;

  const set = (key: keyof Fields) => (e: { target: { value: string } }) =>
    setDraft({ ...draft, [key]: e.target.value });
  const dirty = JSON.stringify(draft) !== stamp;

  const save = () => {
    const changes: TicketDraft = {
      order_type: draft.order_type,
      limit_price: draft.limit_price || null,
      fee: draft.fee,
      reason: draft.reason,
    };
    // An amount gives the quantity; otherwise the quantity is what was typed.
    if (draft.amount.trim()) changes.amount = draft.amount;
    else changes.shares = draft.shares || null;
    // The indicative price keeps its date unless it was typed again.
    if (draft.price !== saved.price) changes.price = draft.price || null;
    // Whatever was typed, the form starts again from what is now stored: "3,0"
    // saved as 3 must not leave the form looking unsaved.
    return act(() => api.updateTicket(ticket.id, changes)).then(() =>
      setDraft(JSON.parse(latest.current) as Fields),
    );
  };

  const unit = decimal(draft.order_type === "limite" ? draft.limit_price : draft.price);
  const shares = decimal(draft.shares);
  const estimate = draft.amount.trim() ? decimal(draft.amount) : unit != null && shares != null ? unit * shares : null;
  const fee = decimal(draft.fee);
  const wide = `${inputClass} w-full num`;

  return (
    <article aria-label={`Brouillon : ${data.sides[ticket.side]} ${ticket.name}`}>
      <Heading ticket={ticket} data={data} />
      <form
        className="mt-4"
        onSubmit={(e) => {
          e.preventDefault();
          save();
        }}
      >
        <div className="grid max-w-[60rem] gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Quantité">
            <input
              inputMode="decimal"
              value={draft.shares}
              onChange={set("shares")}
              disabled={draft.amount.trim() !== ""}
              className={wide}
            />
          </Field>
          <Field label="ou montant, en euros" hint="La quantité en est déduite, arrondie par défaut.">
            <input inputMode="decimal" value={draft.amount} onChange={set("amount")} className={wide} />
          </Field>
          <Field label="Type d'ordre">
            <select value={draft.order_type} onChange={set("order_type")} className={`${inputClass} w-full`}>
              {Object.entries(data.order_types).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </Field>
          {draft.order_type === "limite" && (
            <Field label="Cours limite, en euros">
              <input inputMode="decimal" value={draft.limit_price} onChange={set("limit_price")} className={wide} />
            </Field>
          )}
          <Field
            label="Cours indicatif, en euros"
            hint={
              ticket.price_at
                ? `Relevé le ${date(ticket.price_at)}${ticket.price_at.length > 10 ? ` à ${clock(ticket.price_at)}` : ""}. Le cours d'exécution sera celui du marché.`
                : "Aucun cours connu : le saisir, ou le demander à la source de cours."
            }
          >
            <input inputMode="decimal" value={draft.price} onChange={set("price")} className={wide} />
          </Field>
          <Field label="Frais prévus, en euros">
            <input inputMode="decimal" value={draft.fee} onChange={set("fee")} className={wide} />
          </Field>
        </div>
        <p className="mt-3 text-sm">
          <span className="text-muted">Montant estimé : </span>
          <span className="num">{euro(estimate)}</span>
          {estimate != null && estimate > 0 && fee != null && (
            <span className="text-muted">
              {" "}
              · frais {euro(fee)}, soit {percent(fee / estimate)} du montant
            </span>
          )}
        </p>

        {(ticket.needs_reason || draft.reason !== "") && (
          <div className="mt-4 max-w-[60rem]">
            <Field
              label="Motif écrit"
              hint="Demandé quand une règle est dépassée. Il suivra la transaction dans la page Règles."
            >
              <textarea rows={2} value={draft.reason} onChange={set("reason")} className={`${inputClass} w-full`} />
            </Field>
          </div>
        )}

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button
            type="submit"
            disabled={!dirty}
            className="rounded-md border border-accent px-3 py-1 text-sm text-accent hover:bg-accent-soft disabled:opacity-50"
          >
            Enregistrer
          </button>
          <Quiet
            disabled={busy || dirty}
            onClick={async () => {
              setBusy(true);
              await act(() => api.refreshTicketPrice(ticket.id));
              setBusy(false);
            }}
          >
            {busy ? "Demande du cours…" : "Actualiser le cours"}
          </Quiet>
        </div>
      </form>

      <div className="mt-5">
        <Controls ticket={ticket} />
      </div>

      {ticket.stop && (
        <p className={`mt-4 max-w-[75ch] text-sm ${ticket.blocked ? "font-medium text-alert" : "text-alert"}`}>
          {ticket.stop}
          {ticket.blocked && (
            <>
              {" "}
              <a className="text-accent underline underline-offset-4" href="#/halalitude">
                Relever la Halalitude
              </a>
            </>
          )}
        </p>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <Button
          disabled={!ticket.can_be_ready || dirty}
          onClick={() => act(() => api.setTicketStatus(ticket.id, "pret"))}
        >
          Passer à « prêt »
        </Button>
        {dirty && <span className="text-sm text-muted">Enregistrer d'abord les changements.</span>}
        <span className="ml-auto flex gap-4">
          <LinkButton onClick={() => act(() => api.setTicketStatus(ticket.id, "abandonne"))}>
            Abandonner
          </LinkButton>
          <LinkButton tone="loss" onClick={() => act(() => api.deleteTicket(ticket.id))}>
            Supprimer
          </LinkButton>
        </span>
      </div>
    </article>
  );
}

function ReadyTicket({
  ticket,
  data,
  act,
}: {
  ticket: Ticket;
  data: TicketListing;
  act: (action: () => Promise<unknown>) => Promise<void>;
}) {
  return (
    <article aria-label={`Prêt : ${data.sides[ticket.side]} ${ticket.name}`}>
      <Heading ticket={ticket} data={data} />

      <div className="mt-4 max-w-[60rem] rounded-md border border-line bg-surface p-5">
        <h4 className="text-sm font-medium">À recopier dans Trade Republic</h4>
        <dl className="mt-3 grid gap-x-8 gap-y-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
          <Line label="Titre" value={ticket.name} note={ticket.isin} />
          <Line label="Compte" value={accountName(ticket.account)} />
          <Line label="Sens" value={data.sides[ticket.side]} />
          <Line label="Quantité" value={ticket.shares != null ? quantity(ticket.shares) : "—"} />
          <Line label="Type d'ordre" value={data.order_types[ticket.order_type]} />
          {ticket.order_type === "limite" ? (
            <Line label="Cours limite" value={euro(ticket.limit_price)} />
          ) : (
            <Line
              label="Cours indicatif"
              value={euro(ticket.price)}
              note={`relevé le ${date(ticket.price_at)}`}
            />
          )}
          <Line label="Montant estimé" value={euro(ticket.amount)} />
          <Line
            label="Frais prévus"
            value={euro(ticket.fee)}
            note={ticket.fee_share != null ? `${percent(ticket.fee_share)} du montant` : undefined}
          />
        </dl>
        <p className="mt-3 text-xs text-muted">
          Prêt depuis le {date(ticket.ready_at)}. Le cours d'exécution sera celui du marché au moment
          de l'ordre.
        </p>
      </div>

      {ticket.reason && (
        <p className="mt-4 max-w-[75ch] text-sm">
          <span className="text-muted">Motif écrit : </span>
          {ticket.reason}
        </p>
      )}

      <div className="mt-5">
        <Controls ticket={ticket} />
      </div>

      {ticket.candidates.length > 0 && (
        <div className="mt-5 max-w-[60rem]">
          <p className="text-sm text-alert">
            {ticket.candidates.length === 1
              ? "Une transaction importée pourrait être cet ordre."
              : "Plusieurs transactions importées pourraient être cet ordre."}
          </p>
          <ul className="mt-2 text-sm">
            {ticket.candidates.map((trade) => (
              <li key={trade.transaction_id} className="flex flex-wrap items-baseline gap-x-4 gap-y-1 py-1">
                <span className="num">{tradeLine(trade)}</span>
                <LinkButton onClick={() => act(() => api.matchTicket(ticket.id, trade.transaction_id))}>
                  C'est cet ordre
                </LinkButton>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-4">
        <Quiet onClick={() => act(() => api.setTicketStatus(ticket.id, "brouillon"))}>
          Revenir au brouillon
        </Quiet>
        <LinkButton onClick={() => act(() => api.setTicketStatus(ticket.id, "abandonne"))}>
          Abandonner
        </LinkButton>
      </div>
    </article>
  );
}

const tradeLine = (trade: TicketTrade) =>
  `${date(trade.date)} : ${quantity(trade.shares)} à ${euro(trade.price)}, soit ${euro(trade.amount)}, frais ${euro(trade.fee)}`;

function Line({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div>
      <dt className="text-muted">{label}</dt>
      <dd className="num font-medium">{value}</dd>
      {note && <dd className="text-xs text-muted">{note}</dd>}
    </div>
  );
}

function Executed({
  tickets,
  data,
  act,
}: {
  tickets: Ticket[];
  data: TicketListing;
  act: (action: () => Promise<unknown>) => Promise<void>;
}) {
  const pair = (planned: string, done: string) => (
    <>
      <span className="text-muted">{planned}</span>
      <span className="block">{done}</span>
    </>
  );
  return (
    <TableWrap>
      <table className="data executed-tickets">
        <thead>
          <tr>
            <th>Ordre</th>
            <th>Exécuté le</th>
            <th>Quantité</th>
            <th>Cours</th>
            <th>Montant</th>
            <th>Frais</th>
            <th>Motif</th>
            <th aria-label="Action" />
          </tr>
        </thead>
        <tbody>
          {tickets.map((ticket) => {
            const done = ticket.executed;
            return (
              <tr key={ticket.id}>
                <td>
                  {data.sides[ticket.side]} · {ticket.name}
                  <span className="block text-xs text-muted">{accountName(ticket.account)}</span>
                </td>
                <td className="num">{date(done?.date)}</td>
                <td className="num">
                  {pair(
                    ticket.shares != null ? quantity(ticket.shares) : "—",
                    done ? quantity(done.shares) : "—",
                  )}
                </td>
                <td className="num">{pair(euro(ticket.unit), euro(done?.price))}</td>
                <td className="num">{pair(euro(ticket.amount), euro(done?.amount))}</td>
                <td className="num">{pair(euro(ticket.fee), euro(done?.fee))}</td>
                <td>{ticket.reason ?? <span className="text-muted">—</span>}</td>
                <td>
                  <LinkButton onClick={() => act(() => api.matchTicket(ticket.id, null))}>
                    Défaire
                  </LinkButton>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-muted">
        Dans chaque case : le prévu en gris, l'exécuté en dessous. « Défaire » rend le ticket à
        l'état « prêt » si la transaction n'était pas la bonne.
      </p>
    </TableWrap>
  );
}

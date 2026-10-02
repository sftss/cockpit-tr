import { useEffect, useRef, useState } from "react";
import {
  api,
  type AssistantStatus,
  type AssistantTurn,
  type ContextDocument,
  type Conversation,
  type ConversationSummary,
  type MonthUsage,
} from "../api";
import { Markdown } from "../components/Markdown";
import { Button, Field, Notice, PageTitle, Quiet, Section, inputClass } from "../components/ui";
import { date, euro, number, percent } from "../format";

const SUGGESTIONS = [
  "Où en sont mes règles ce trimestre ?",
  "Quelles lignes sont à revérifier côté Halalitude ?",
  "Résume mes frais depuis l'ouverture, par trimestre.",
];

const dollars = (value: number) =>
  `${new Intl.NumberFormat("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 4 }).format(value)} $`;

type Live = { question: string; text: string; activity: { label: string; writes?: boolean }[] };

export function Assistant() {
  const [status, setStatus] = useState<AssistantStatus | null>(null);
  const [threads, setThreads] = useState<ConversationSummary[]>([]);
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [live, setLive] = useState<Live | null>(null);
  const [draft, setDraft] = useState("");
  const [webSearch, setWebSearch] = useState(false);
  const [model, setModel] = useState("");
  const [error, setError] = useState<string | null>(null);
  const end = useRef<HTMLDivElement>(null);

  const loadThreads = () => api.conversations().then(setThreads).catch(() => setThreads([]));
  useEffect(() => {
    api
      .assistantStatus()
      .then((s) => {
        setStatus(s);
        setModel(s.default_model);
      })
      .catch((e: Error) => setError(e.message));
    loadThreads();
  }, []);
  useEffect(() => {
    end.current?.scrollIntoView({ block: "nearest" });
  }, [live?.text, live?.activity.length, conversation?.turns.length]);

  const open = async (id: number) => {
    setError(null);
    try {
      const loaded = await api.conversation(id);
      setConversation(loaded);
      setModel(loaded.model);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const send = async (text: string) => {
    const question = text.trim();
    if (!question || live || !status) return;
    setError(null);
    setDraft("");
    try {
      const target = conversation ?? (await api.createConversation(model));
      setConversation(target);
      setLive({ question, text: "", activity: [] });
      await api.sendMessage(target.id, { text: question, web_search: webSearch, model }, (event) => {
        if (event.type === "text") {
          setLive((now) => now && { ...now, text: now.text + event.text });
        } else if (event.type === "activity") {
          setLive((now) => now && { ...now, activity: [...now.activity, event] });
        } else if (event.type === "error") {
          setError(event.message);
        } else {
          if (event.conversation) setConversation(event.conversation);
          setStatus((now) => now && { ...now, month: event.month });
        }
      });
    } catch (e) {
      setError((e as Error).message);
      setDraft(question);
    } finally {
      setLive(null);
      loadThreads();
    }
  };

  const remove = async (id: number) => {
    await api.deleteConversation(id).catch(() => undefined);
    if (conversation?.id === id) setConversation(null);
    loadThreads();
  };

  if (!status) return error ? <Notice tone="error">{error}</Notice> : null;

  const turns = conversation?.turns ?? [];
  return (
    <>
      <PageTitle lead="L'assistant lit les données locales à la demande et ne passe aucun ordre. Chaque question envoie à l'API d'Anthropic les données de portefeuille utiles à la réponse ; l'or physique n'en fait jamais partie.">
        Assistant
      </PageTitle>

      {!status.configured ? (
        <KeySetup onSaved={setStatus} />
      ) : (
        <div className="grid gap-x-10 gap-y-8 lg:grid-cols-[220px_minmax(0,1fr)]">
          <nav aria-label="Discussions" className="text-sm">
            <Quiet
              onClick={() => {
                setConversation(null);
                setError(null);
              }}
            >
              Nouvelle discussion
            </Quiet>
            <ul className="mt-4 border-t border-line">
              {threads.map((thread) => (
                <li key={thread.id} className="flex items-baseline gap-2 border-b border-line py-2">
                  <button
                    type="button"
                    onClick={() => open(thread.id)}
                    aria-current={conversation?.id === thread.id ? "true" : undefined}
                    className={`min-w-0 flex-1 truncate text-left hover:text-accent ${
                      conversation?.id === thread.id ? "font-medium" : ""
                    }`}
                    title={thread.title}
                  >
                    {thread.title}
                    <span className="block text-xs text-muted">{date(thread.updated_at)}</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => remove(thread.id)}
                    aria-label={`Supprimer la discussion « ${thread.title} »`}
                    className="text-xs text-muted hover:text-loss"
                  >
                    Supprimer
                  </button>
                </li>
              ))}
            </ul>
            <Month usage={status.month} />
          </nav>

          <div className="min-w-0">
            {turns.length === 0 && !live && (
              <div className="mb-8">
                <p className="max-w-[60ch] text-muted">
                  Une question sur le portefeuille, les règles, la Halalitude, la feuille de route
                  ou une fiche du jour. Par exemple :
                </p>
                <ul className="mt-3 space-y-2">
                  {SUGGESTIONS.map((suggestion) => (
                    <li key={suggestion}>
                      <button
                        type="button"
                        onClick={() => send(suggestion)}
                        className="text-left text-accent underline decoration-line underline-offset-4 hover:decoration-accent"
                      >
                        {suggestion}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <ol className="space-y-8">
              {turns.map((turn, index) =>
                turn.role === "user" ? (
                  <li key={index}>
                    <Question text={turn.text} />
                  </li>
                ) : (
                  <li key={index}>
                    <Answer turn={turn} models={status.models} />
                  </li>
                ),
              )}
              {live && (
                <>
                  <li>
                    <Question text={live.question} />
                  </li>
                  <li aria-live="polite">
                    <Activity items={live.activity.map((a) => ({ ...a, writes: !!a.writes }))} />
                    {live.text ? (
                      <Markdown text={live.text} />
                    ) : (
                      <p className="text-muted">L'assistant réfléchit…</p>
                    )}
                  </li>
                </>
              )}
            </ol>
            <div ref={end} />

            {error && (
              <div className="mt-6">
                <Notice tone="error">{error}</Notice>
              </div>
            )}

            <form
              className="mt-8 border-t border-line pt-5"
              onSubmit={(e) => {
                e.preventDefault();
                send(draft);
              }}
            >
              <textarea
                aria-label="Message à l'assistant"
                rows={3}
                value={draft}
                placeholder="Écrire une question. Entrée pour envoyer, Maj + Entrée pour aller à la ligne."
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    send(draft);
                  }
                }}
                className={`${inputClass} w-full px-3 py-2`}
              />
              <div className="mt-3 flex flex-wrap items-center gap-x-6 gap-y-3 text-sm">
                <button
                  type="submit"
                  disabled={!!live || !draft.trim()}
                  className="rounded-md bg-accent px-4 py-2 font-medium text-surface hover:opacity-90 disabled:opacity-50"
                >
                  {live ? "Réponse en cours…" : "Envoyer"}
                </button>
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={webSearch}
                    onChange={(e) => setWebSearch(e.target.checked)}
                    className="size-4 accent-[var(--accent)]"
                  />
                  Recherche web <span className="text-muted">(0,01 $ par recherche)</span>
                </label>
                <label className="flex items-center gap-2">
                  <span className="text-muted">Modèle</span>
                  <select value={model} onChange={(e) => setModel(e.target.value)} className={inputClass}>
                    {status.models.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            </form>
          </div>
        </div>
      )}

      <div className="mt-14">
        <Settings status={status} onChange={setStatus} />
      </div>
    </>
  );
}

function Question({ text }: { text: string }) {
  return (
    <p className="max-w-[70ch] whitespace-pre-wrap rounded-md bg-accent-soft px-4 py-3">{text}</p>
  );
}

function Activity({ items }: { items: { label: string; writes: boolean }[] }) {
  if (items.length === 0) return null;
  return (
    <ul className="mb-3 text-xs text-muted">
      {items.map((item, index) => (
        <li key={index} className={item.writes ? "font-medium text-accent" : undefined}>
          {item.label}
        </li>
      ))}
    </ul>
  );
}

function Answer({ turn, models }: { turn: AssistantTurn; models: { id: string; label: string }[] }) {
  const label = models.find((m) => m.id === turn.model)?.label ?? turn.model ?? "";
  return (
    <div>
      <Activity items={turn.activity} />
      <Markdown text={turn.text} />
      {turn.sources.length > 0 && (
        <div className="mt-3 text-sm">
          <p className="text-muted">Sources</p>
          <ul>
            {turn.sources.map((source) => (
              <li key={source.url}>
                <a
                  className="text-accent underline underline-offset-4"
                  href={source.url}
                  target="_blank"
                  rel="noreferrer noopener"
                >
                  {source.title || source.url}
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}
      <p className="num mt-3 text-xs text-muted">
        {label}, {number(turn.usage.tokens_in)} tokens lus, {number(turn.usage.tokens_out)} écrits
        {turn.usage.web_searches > 0 && `, ${turn.usage.web_searches} recherches web`}, environ{" "}
        {dollars(turn.usage.cost_usd)}
      </p>
    </div>
  );
}

/** Spending of the month against the budget: shown, never blocking. */
function Month({ usage }: { usage: MonthUsage }) {
  const near = usage.share_of_budget >= 0.8;
  const spent = usage.cost_eur != null ? euro(usage.cost_eur) : dollars(usage.cost_usd);
  return (
    <p className={`mt-5 text-xs ${near ? "text-alert" : "text-muted"}`}>
      Ce mois-ci : environ {spent} sur {euro(usage.budget_eur)} de budget (
      {percent(usage.share_of_budget)}), {usage.calls} appels.
      {near && " Le budget est presque atteint."}
    </p>
  );
}

function KeySetup({ onSaved }: { onSaved: (status: AssistantStatus) => void }) {
  const [key, setKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const save = async () => {
    try {
      setError(null);
      onSaved(await api.saveKey(key));
      setKey("");
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return (
    <Section
      title="Enregistrer la clé d'API"
      note="La clé se crée dans la console Anthropic. Elle est rangée dans le gestionnaire d'identifiants de Windows : ni dans la base, ni dans un fichier, et l'application ne la réaffiche jamais."
    >
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Clé d'API Anthropic">
          <input
            type="password"
            autoComplete="off"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder="sk-ant-…"
            className={`${inputClass} w-96 max-w-full`}
          />
        </Field>
        <Button onClick={save} disabled={!key.trim()}>
          Enregistrer la clé
        </Button>
      </div>
      {error && (
        <div className="mt-4">
          <Notice tone="error">{error}</Notice>
        </div>
      )}
    </Section>
  );
}

function Settings({
  status,
  onChange,
}: {
  status: AssistantStatus;
  onChange: (status: AssistantStatus) => void;
}) {
  const [budget, setBudget] = useState(String(status.month.budget_eur).replace(".", ","));
  const [docs, setDocs] = useState<ContextDocument[]>([]);
  const [editing, setEditing] = useState<{ title: string; content: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadDocs = () => api.contextDocuments().then(setDocs).catch(() => setDocs([]));
  useEffect(() => {
    loadDocs();
  }, []);

  const act = async (action: () => Promise<unknown>) => {
    try {
      setError(null);
      await action();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <details>
      <summary className="cursor-pointer font-display text-xl">Réglages de l'assistant</summary>
      <div className="mt-6 space-y-8">
        {error && <Notice tone="error">{error}</Notice>}

        <div className="flex flex-wrap items-end gap-x-8 gap-y-4">
          <Field label="Modèle par défaut">
            <select
              value={status.default_model}
              onChange={(e) =>
                act(async () => onChange(await api.saveAssistantSettings({ model: e.target.value })))
              }
              className={inputClass}
            >
              {status.models.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Budget mensuel, en euros" hint="Un repère : rien n'est bloqué.">
            <input
              inputMode="decimal"
              value={budget}
              onChange={(e) => setBudget(e.target.value)}
              onBlur={() =>
                act(async () => onChange(await api.saveAssistantSettings({ budget_eur: budget })))
              }
              className={`${inputClass} num w-28 text-right`}
            />
          </Field>
          {status.configured && (
            <div className="text-sm">
              <p className="text-muted">
                Clé d'API :{" "}
                {status.key_source === "coffre"
                  ? "rangée dans le gestionnaire d'identifiants"
                  : "lue dans la variable d'environnement ANTHROPIC_API_KEY"}
              </p>
              {status.key_source === "coffre" && (
                <button
                  type="button"
                  onClick={() => act(async () => onChange(await api.deleteKey()))}
                  className="mt-1 text-loss hover:underline"
                >
                  Retirer la clé
                </button>
              )}
            </div>
          )}
        </div>

        <div>
          <h3 className="font-display text-lg">Consignes et documents de référence</h3>
          <p className="mt-1 max-w-[75ch] text-sm text-muted">
            Ce que l'assistant lit avant chaque discussion : consignes personnelles, méthode,
            dernière revue. Ces textes restent sur cet ordinateur et partent vers l'API avec chaque
            question.
          </p>
          <ul className="mt-3 border-t border-line">
            {docs.map((doc) => (
              <li key={doc.id} className="flex flex-wrap items-baseline gap-x-4 border-b border-line py-2 text-sm">
                <span className="min-w-0 flex-1">{doc.title}</span>
                <span className="num text-xs text-muted">
                  {number(doc.content.length)} caractères, modifié le {date(doc.updated_at)}
                </span>
                <button
                  type="button"
                  onClick={() => setEditing({ title: doc.title, content: doc.content })}
                  className="text-accent hover:underline"
                >
                  Modifier
                </button>
                <button
                  type="button"
                  onClick={() => act(async () => {
                    await api.deleteContextDocument(doc.id);
                    await loadDocs();
                  })}
                  aria-label={`Supprimer le document ${doc.title}`}
                  className="text-loss hover:underline"
                >
                  Supprimer
                </button>
              </li>
            ))}
          </ul>
          {editing ? (
            <form
              className="mt-4 rounded-md border border-line bg-surface p-5"
              onSubmit={(e) => {
                e.preventDefault();
                act(async () => {
                  await api.saveContextDocument(editing.title, editing.content);
                  setEditing(null);
                  await loadDocs();
                });
              }}
            >
              <Field label="Titre">
                <input
                  required
                  value={editing.title}
                  onChange={(e) => setEditing({ ...editing, title: e.target.value })}
                  className={`${inputClass} w-full`}
                />
              </Field>
              <div className="mt-4">
                <Field label="Contenu">
                  <textarea
                    required
                    rows={12}
                    value={editing.content}
                    onChange={(e) => setEditing({ ...editing, content: e.target.value })}
                    className={`${inputClass} w-full font-mono text-[13px]`}
                  />
                </Field>
              </div>
              <div className="mt-4 flex gap-3">
                <button
                  type="submit"
                  className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-surface hover:opacity-90"
                >
                  Enregistrer le document
                </button>
                <Quiet onClick={() => setEditing(null)}>Annuler</Quiet>
              </div>
            </form>
          ) : (
            <div className="mt-4">
              <Quiet onClick={() => setEditing({ title: "", content: "" })}>Ajouter un document</Quiet>
            </div>
          )}
        </div>
      </div>
    </details>
  );
}

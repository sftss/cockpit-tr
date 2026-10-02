import { useEffect, useState } from "react";
import { api, type JournalDraft, type JournalEntry } from "../api";
import { Button, Field, Notice, PageTitle, Quiet, inputClass } from "../components/ui";
import { date, plural, today } from "../format";

const draftOf = (entry: JournalEntry): JournalDraft => ({
  title: entry.title,
  body: entry.body ?? "",
  decided_on: entry.decided_on,
});

export function Journal() {
  const [entries, setEntries] = useState<JournalEntry[] | null>(null);
  const [editing, setEditing] = useState<number | "new" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () =>
    api
      .journal()
      .then((data) => {
        setEntries(data);
        setError(null);
      })
      .catch((e: Error) => setError(e.message));
  useEffect(() => {
    load();
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

  if (!entries) return error ? <Notice tone="error">{error}</Notice> : null;
  return (
    <>
      <PageTitle lead="Ce qui a été décidé, quand et pourquoi. L'assistant lit ce journal ; les notes qu'il y ajoute sont marquées comme venant de lui.">
        Journal : {entries.length === 0 ? "aucune note" : plural(entries.length, "note", "notes")}
      </PageTitle>

      {error && (
        <div className="mb-6">
          <Notice tone="error">{error}</Notice>
        </div>
      )}

      <div className="mb-10">
        {editing === "new" ? (
          <EntryForm
            initial={{ title: "", body: "", decided_on: today() }}
            save={(draft) => act(() => api.addJournalEntry(draft))}
            cancel={() => setEditing(null)}
          />
        ) : (
          <Button onClick={() => setEditing("new")}>Ajouter une note</Button>
        )}
      </div>

      {entries.length === 0 ? (
        <p className="max-w-[65ch] text-muted">
          Le journal est vide. Y noter une décision au moment où elle est prise permet de la relire
          à la revue suivante, avec son motif d'alors.
        </p>
      ) : (
        <ul className="border-t border-line">
          {entries.map((entry) => (
            <li key={entry.id} className="border-b border-line py-5">
              {editing === entry.id ? (
                <EntryForm
                  initial={draftOf(entry)}
                  save={(draft) => act(() => api.updateJournalEntry(entry.id, draft))}
                  cancel={() => setEditing(null)}
                  remove={() => act(() => api.deleteJournalEntry(entry.id))}
                />
              ) : (
                <div className="grid gap-x-10 gap-y-2 md:grid-cols-[150px_minmax(0,1fr)_auto]">
                  <p className="num text-sm text-muted">
                    {date(entry.decided_on)}
                    {entry.author === "assistant" && (
                      <span className="block text-accent">note de l'assistant</span>
                    )}
                  </p>
                  <div className="max-w-[70ch]">
                    <h2 className="font-display text-lg leading-snug">{entry.title}</h2>
                    {entry.body && <p className="mt-1 whitespace-pre-line text-sm">{entry.body}</p>}
                  </div>
                  <button
                    type="button"
                    onClick={() => setEditing(entry.id)}
                    aria-label={`Modifier la note « ${entry.title} »`}
                    className="self-start text-sm text-accent hover:underline"
                  >
                    Modifier
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

function EntryForm({
  initial,
  save,
  cancel,
  remove,
}: {
  initial: JournalDraft;
  save: (draft: JournalDraft) => void;
  cancel: () => void;
  remove?: () => void;
}) {
  const [draft, setDraft] = useState(initial);
  return (
    <form
      aria-label="Note du journal"
      className="max-w-3xl rounded-md border border-line bg-surface p-5"
      onSubmit={(e) => {
        e.preventDefault();
        save(draft);
      }}
    >
      <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_170px]">
        <Field label="Décision">
          <input
            required
            value={draft.title}
            onChange={(e) => setDraft({ ...draft, title: e.target.value })}
            className={`${inputClass} w-full`}
          />
        </Field>
        <Field label="Date">
          <input
            type="date"
            value={draft.decided_on}
            max={today()}
            onChange={(e) => setDraft({ ...draft, decided_on: e.target.value })}
            className={`${inputClass} num w-full`}
          />
        </Field>
      </div>
      <div className="mt-4">
        <Field label="Motif">
          <textarea
            rows={4}
            value={draft.body}
            onChange={(e) => setDraft({ ...draft, body: e.target.value })}
            className={`${inputClass} w-full`}
          />
        </Field>
      </div>
      <div className="mt-5 flex flex-wrap items-center gap-3">
        <button
          type="submit"
          className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-surface hover:opacity-90"
        >
          Enregistrer la note
        </button>
        <Quiet onClick={cancel}>Annuler</Quiet>
        {remove && (
          <button type="button" onClick={remove} className="ml-auto text-sm text-loss hover:underline">
            Supprimer la note
          </button>
        )}
      </div>
    </form>
  );
}

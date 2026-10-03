import { useEffect, useState } from "react";
import { api, type Review, type ReviewData, type ReviewListing } from "../api";
import { Markdown } from "../components/Markdown";
import { Button, Notice, PageTitle, Quiet, Result, Section, TableWrap, inputClass } from "../components/ui";
import { accountName, date, euro, percent, plural, signedEuro, signedPercent } from "../format";

export function Reviews() {
  const [listing, setListing] = useState<ReviewListing | null>(null);
  const [quarter, setQuarter] = useState<string | null>(null);
  const [review, setReview] = useState<Review | null>(null);
  const [busy, setBusy] = useState<"generate" | "comment" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = () =>
    api
      .reviews()
      .then((data) => {
        setListing(data);
        return data;
      })
      .catch((e: Error) => {
        setError(e.message);
        return null;
      });

  useEffect(() => {
    refresh().then((data) => {
      if (data) setQuarter(data.reviews[0]?.quarter ?? data.due?.quarter ?? data.quarters[0]?.quarter ?? null);
    });
  }, []);

  useEffect(() => {
    if (!quarter || !listing) return;
    setError(null);
    if (!listing.reviews.some((r) => r.quarter === quarter)) return setReview(null);
    api
      .review(quarter)
      .then(setReview)
      .catch((e: Error) => setError(e.message));
  }, [quarter, listing]);

  const run = async (kind: "generate" | "comment", action: () => Promise<Review>) => {
    setBusy(kind);
    setError(null);
    try {
      setReview(await action());
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  if (!listing) return error ? <Notice tone="error">{error}</Notice> : null;
  if (listing.quarters.length === 0) {
    return <PageTitle lead="Une revue se calcule à partir des transactions importées.">Revues : aucune transaction</PageTitle>;
  }
  const label = listing.quarters.find((q) => q.quarter === quarter)?.name ?? "";
  const shown = review && review.quarter === quarter ? review : null;

  return (
    <>
      <PageTitle lead="Une revue arrête les chiffres d'un trimestre : comptes, activité face aux règles, frais, écarts. L'application calcule ; la lecture se fait ensuite, avec l'aide de l'assistant sur demande. Ce n'est pas un conseil en investissement.">
        {shown ? `Revue du ${shown.data.name} : ${headline(shown.data)}` : `Revue du ${label} : à générer`}
      </PageTitle>

      {listing.due && listing.due.quarter !== quarter && (
        <div className="mb-6">
          <Notice>
            La revue du {listing.due.name} n'a pas encore été faite.{" "}
            <button type="button" className="underline" onClick={() => setQuarter(listing.due!.quarter)}>
              L'ouvrir
            </button>
          </Notice>
        </div>
      )}

      <div className="mb-8 flex flex-wrap items-center gap-4">
        <label className="flex items-center gap-2 text-sm">
          <span className="text-muted">Trimestre</span>
          <select value={quarter ?? ""} onChange={(e) => setQuarter(e.target.value)} className={inputClass}>
            {listing.quarters.map((q) => (
              <option key={q.quarter} value={q.quarter}>
                {q.name}
                {listing.reviews.some((r) => r.quarter === q.quarter) ? "" : " (pas de revue)"}
              </option>
            ))}
          </select>
        </label>
        {quarter && (
          <Button onClick={() => run("generate", () => api.generateReview(quarter))} disabled={busy !== null}>
            {busy === "generate" ? "Calcul en cours…" : shown ? "Actualiser les chiffres" : "Générer la revue"}
          </Button>
        )}
        {shown && (
          <a className="text-sm text-accent underline underline-offset-4" href={`/api/reviews/${shown.quarter}/export`}>
            Exporter en Markdown
          </a>
        )}
      </div>

      {error && (
        <div className="mb-6">
          <Notice tone="error">{error}</Notice>
        </div>
      )}

      {shown && (
        <>
          <p className="-mt-4 mb-10 max-w-[80ch] text-sm text-muted">
            Du {date(shown.data.from)} au {date(shown.data.to)}, chiffres arrêtés le {date(shown.generated_at)}
            {shown.data.complete ? "." : " : le trimestre n'est pas terminé."} Actualiser remplace les chiffres et
            efface le commentaire écrit sur les anciens ; les conclusions restent.
          </p>
          <Figures data={shown.data} />
          <Commentary review={shown} busy={busy === "comment"} ask={() => run("comment", () => api.commentReview(shown.quarter))} />
          <Conclusions key={shown.quarter + shown.generated_at} review={shown} saved={setReview} fail={setError} />
        </>
      )}
    </>
  );
}

const headline = (data: ReviewData) => {
  const orders = plural(data.fees.manual_orders, "ordre manuel", "ordres manuels");
  return data.performance.available ? `${signedEuro(data.performance.gain)} sur le trimestre, ${orders}` : orders;
};

function Figures({ data }: { data: ReviewData }) {
  const perf = data.performance;
  return (
    <>
      <Section title="Comptes" note={`Au ${date(data.as_of)}.`}>
        <TableWrap>
          <table className="data max-w-4xl">
            <thead>
              <tr>
                <th>Compte</th>
                <th>Lignes</th>
                <th>Capital net engagé</th>
                <th>Valeur</th>
                <th>Résultat latent</th>
                <th>Performance</th>
              </tr>
            </thead>
            <tbody>
              {data.accounts.map((a) => (
                <tr key={a.account}>
                  <td>{a.label}</td>
                  <td className="num">{a.open_lines}</td>
                  <td className="num">{euro(a.net_invested)}</td>
                  <td className="num">{euro(a.value)}</td>
                  <td>
                    <Result value={a.latent}>{signedEuro(a.latent)}</Result>
                  </td>
                  <td>
                    <Result value={a.performance}>{signedPercent(a.performance)}</Result>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      </Section>

      <Section title="Le trimestre" note="La performance neutralise les achats et les ventes : elle mesure l'évolution des titres détenus, pas l'argent ajouté.">
        {perf.available ? (
          <>
            <dl className="grid max-w-4xl gap-x-10 gap-y-5 sm:grid-cols-2 lg:grid-cols-4">
              <Fact label="Valeur au début" value={euro(perf.start_value)} />
              <Fact label="Achats, ventes" value={`${euro(perf.bought)}, ${euro(perf.sold)}`} />
              <Fact label="Valeur à la fin" value={euro(perf.end_value)} />
              <Fact label="Gain ou perte du trimestre" value={signedEuro(perf.gain)} loss={perf.gain < 0} />
              <Fact label="Performance du portefeuille" value={signedPercent(perf.change)} loss={(perf.change ?? 0) < 0} />
              {perf.benchmark && (
                <Fact
                  label={`${perf.benchmark.label}, même période`}
                  value={signedPercent(perf.benchmark.change)}
                  loss={(perf.benchmark.change ?? 0) < 0}
                />
              )}
            </dl>
            {perf.at_cost > 0 && (
              <p className="mt-4 text-sm text-muted">
                {euro(perf.at_cost)} sont comptés au prix de revient, faute de cours.
              </p>
            )}
          </>
        ) : (
          <p className="text-muted">Rien n'était détenu sur ce trimestre.</p>
        )}
      </Section>

      <Section title="Activité face aux règles">
        <TableWrap>
          <table className="data review-rules max-w-4xl">
            <thead>
              <tr>
                <th>Règle</th>
                <th>Constaté</th>
                <th>Prévu</th>
                <th>Écarts</th>
              </tr>
            </thead>
            <tbody>
              {data.counters.map((c) => (
                <tr key={c.kind}>
                  <td>{c.label}</td>
                  <td className="num">{c.count}</td>
                  <td>{c.limit}</td>
                  <td className="num">{c.breaches > 0 ? <span className="text-alert">{c.breaches}</span> : 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
        {data.deviations.length > 0 ? (
          <div className="mt-8">
            <h3 className="mb-2 font-medium">
              {plural(data.deviations.length, "écart", "écarts")}, dont{" "}
              {data.deviations.filter((d) => !d.reason).length} sans motif
            </h3>
            <TableWrap>
              <table className="data review-text max-w-5xl">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Titre</th>
                    <th>Écart</th>
                    <th>Motif</th>
                  </tr>
                </thead>
                <tbody>
                  {data.deviations.map((d) => (
                    <tr key={d.date + d.name + d.details.join()}>
                      <td className="num">{date(d.date)}</td>
                      <td>{d.name || "—"}</td>
                      <td>{d.details.join(" ; ")}</td>
                      <td>{d.reason ?? <span className="text-alert">sans motif</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableWrap>
            <p className="mt-3 text-sm">
              <a className="text-accent underline underline-offset-4" href="#/regles">
                Écrire les motifs
              </a>
              <span className="text-muted">, puis actualiser les chiffres de la revue.</span>
            </p>
          </div>
        ) : (
          <p className="mt-4 text-muted">Aucun écart aux règles sur le trimestre.</p>
        )}
      </Section>

      <Section title="Frais">
        <dl className="grid max-w-4xl gap-x-10 gap-y-5 sm:grid-cols-2 lg:grid-cols-4">
          <Fact label="Ordres manuels" value={String(data.fees.manual_orders)} note={`${data.fees.free_trades} exécutions sans frais`} />
          <Fact label="Frais d'ordre" value={euro(data.fees.order_fees)} note={`${percent(data.fees.share_of_amount)} du montant des ordres`} />
          <Fact label="Frais de rechargement" value={euro(data.fees.deposit_fees)} />
          <Fact label="Frais depuis l'ouverture" value={euro(data.fees.total_since_start)} note={`${percent(data.fees.share_of_capital)} du capital apporté`} />
        </dl>
        <p className="mt-5 max-w-[80ch] text-sm text-muted">
          Ordres manuels par trimestre, du plus ancien au {data.name} :{" "}
          <span className="num text-ink">{data.rotation.map((q) => q.manual_orders).join(" / ")}</span>.
        </p>
      </Section>

      <Section title="Lignes ouvertes et soldées">
        <p className="max-w-[80ch]">
          <span className="text-muted">Nouvelles lignes :</span>{" "}
          {data.opened.length > 0 ? data.opened.join(", ") : "aucune"}.
        </p>
        {data.closed.length > 0 ? (
          <div className="mt-4">
            <TableWrap>
              <table className="data review-text max-w-3xl">
                <thead>
                  <tr>
                    <th>Ligne soldée</th>
                    <th>Compte</th>
                    <th>Durée</th>
                    <th>Résultat net</th>
                  </tr>
                </thead>
                <tbody>
                  {data.closed.map((c) => (
                    <tr key={c.account + c.name}>
                      <td>{c.name}</td>
                      <td>{accountName(c.account)}</td>
                      <td className="num">{c.holding_days != null ? `${c.holding_days} j` : "—"}</td>
                      <td>
                        <Result value={c.net}>
                          {signedEuro(c.net)} <span className="text-xs">({signedPercent(c.net_pct)})</span>
                        </Result>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableWrap>
          </div>
        ) : (
          <p className="mt-2 text-muted">Aucune ligne soldée.</p>
        )}
      </Section>

      <Section
        title="Portefeuille"
        note={`Au ${date(data.as_of)}. Poids calculés sur ${data.weights_basis === "value" ? "la valeur" : "le prix de revient"}.`}
      >
        <TableWrap>
          <table className="data review-text max-w-4xl">
            <thead>
              <tr>
                <th>Titre</th>
                <th>Compte</th>
                <th>Poids</th>
                <th>Résultat latent</th>
                <th>Halalitude</th>
              </tr>
            </thead>
            <tbody>
              {data.positions.map((p) => (
                <tr key={p.account + p.name}>
                  <td>{p.name}</td>
                  <td>{accountName(p.account)}</td>
                  <td className="num">{percent(p.weight)}</td>
                  <td>
                    <Result value={p.latent_pct}>{signedPercent(p.latent_pct)}</Result>
                  </td>
                  <td>
                    {p.halalitude === "Halal" && p.halalitude_state === "a_jour" ? (
                      p.halalitude
                    ) : (
                      <span className="text-alert">
                        {p.halalitude}
                        {p.halalitude_state === "a_reverifier" && ", à revérifier"}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
        <p className="mt-3 max-w-[80ch] text-sm text-muted">
          {data.halalitude.attention.length === 0
            ? "Toutes les lignes détenues ont un statut halal à jour."
            : `${plural(data.halalitude.attention.length, "ligne détenue demande", "lignes détenues demandent")} un regard : statut manquant, à revérifier, douteux ou haram.`}
        </p>
      </Section>

      {data.roadmap.length > 0 && (
        <Section title="Feuille de route">
          <TableWrap>
            <table className="data max-w-3xl">
              <thead>
                <tr>
                  <th>Cible</th>
                  <th>Statut</th>
                  <th>Cours d'entrée</th>
                  <th>Dernier cours</th>
                  <th>Atteint</th>
                </tr>
              </thead>
              <tbody>
                {data.roadmap.map((item) => (
                  <tr key={item.name}>
                    <td>{item.name}</td>
                    <td>{item.status}</td>
                    <td className="num">{euro(item.entry_price)}</td>
                    <td className="num">{euro(item.last_price)}</td>
                    <td>{item.reached ? "oui" : "non"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        </Section>
      )}

      {data.sheets.length > 0 && (
        <Section title="Fiches du trimestre" note="Une note trie des candidats ; elle ne dit rien de la Halalitude.">
          <TableWrap>
            <table className="data max-w-3xl">
              <thead>
                <tr>
                  <th>Entreprise</th>
                  <th>Fiche du</th>
                  <th>Note sur 20</th>
                  <th>Libellé</th>
                </tr>
              </thead>
              <tbody>
                {data.sheets.map((s) => (
                  <tr key={s.date + s.name}>
                    <td>{s.name ?? "—"}</td>
                    <td className="num">{date(s.date)}</td>
                    <td className="num">{s.score ?? "—"}</td>
                    <td>{s.label ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        </Section>
      )}

      <Section title="Repères pour le trimestre suivant" note="Ce que le trimestre a compté, face à la règle en vigueur pour le suivant.">
        <TableWrap>
          <table className="data review-rules max-w-4xl">
            <thead>
              <tr>
                <th>Indicateur</th>
                <th>{data.name}</th>
                <th>Règle du trimestre suivant</th>
              </tr>
            </thead>
            <tbody>
              {data.counters.map((c) => (
                <tr key={c.kind}>
                  <td>{c.label}</td>
                  <td className="num">{c.count}</td>
                  <td>{c.next_limit}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      </Section>
    </>
  );
}

function Commentary({ review, busy, ask }: { review: Review; busy: boolean; ask: () => void }) {
  return (
    <Section
      title="Commentaire de l'assistant"
      note="À la demande. La revue est envoyée à l'API, comme un message à l'assistant : quelques centimes, comptés dans la consommation du mois."
    >
      {review.commentary ? (
        <>
          <Markdown text={review.commentary} />
          <p className="mt-4 text-sm text-muted">
            Écrit le {date(review.commentary_at)}. La discussion se poursuit dans la page{" "}
            <a className="text-accent underline underline-offset-4" href="#/assistant">
              Assistant
            </a>
            .
          </p>
        </>
      ) : (
        <Quiet onClick={ask} disabled={busy}>
          {busy ? "Rédaction en cours, jusqu'à une minute…" : "Demander le commentaire"}
        </Quiet>
      )}
    </Section>
  );
}

function Conclusions({
  review,
  saved,
  fail,
}: {
  review: Review;
  saved: (review: Review) => void;
  fail: (message: string) => void;
}) {
  const [text, setText] = useState(review.conclusions ?? "");
  const [state, setState] = useState<"idle" | "saving" | "saved">("idle");
  const save = async () => {
    setState("saving");
    try {
      saved(await api.saveConclusions(review.quarter, text));
      setState("saved");
    } catch (e) {
      fail((e as Error).message);
      setState("idle");
    }
  };
  return (
    <Section title="Mes conclusions" note="Ce qui est retenu et décidé pour le trimestre suivant. Elles restent quand les chiffres sont actualisés.">
      <textarea
        aria-label="Mes conclusions"
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setState("idle");
        }}
        rows={6}
        className={`${inputClass} w-full max-w-[80ch] text-left`}
      />
      <div className="mt-3 flex items-center gap-3">
        <Quiet onClick={save} disabled={state === "saving" || text === (review.conclusions ?? "")}>
          Enregistrer
        </Quiet>
        {state === "saved" && <span className="text-sm text-muted">Enregistré.</span>}
      </div>
    </Section>
  );
}

function Fact({ label, value, note, loss }: { label: string; value: string; note?: string; loss?: boolean }) {
  return (
    <div className="border-t border-line pt-3">
      <dt className="text-sm text-muted">{label}</dt>
      <dd className={`num text-lg ${loss ? "text-loss" : ""}`}>{value}</dd>
      {note && <dd className="text-sm text-muted">{note}</dd>}
    </div>
  );
}

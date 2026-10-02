import { useEffect, useState } from "react";
import { api, type Watch as WatchData, type WatchSource, type WatchTitle } from "../api";
import { Notice, PageTitle, Section, TableWrap, inputClass } from "../components/ui";
import { date, plural } from "../format";

const FOLLOWED = { ligne: "ligne détenue", cible: "cible de la feuille de route" } as const;

const hasNews = (title: WatchTitle) => title.faits.length > 0 || Boolean(title.a_regarder);

/** How many followed companies have news: the one figure the home page shows. */
export const followedNews = (titles: WatchTitle[]) =>
  titles.filter((title) => title.suivi && hasNews(title)).length;

export function Watch() {
  const [data, setData] = useState<WatchData | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = (week?: string) =>
    api
      .watch(week)
      .then((result) => {
        setData(result);
        setError(null);
      })
      .catch((e: Error) => setError(e.message));
  useEffect(() => {
    load();
  }, []);

  if (!data) return error ? <Notice tone="error">{error}</Notice> : null;
  const report = data.report;
  if (!report) {
    return (
      <>
        <PageTitle lead="Chaque samedi matin, une veille relève les faits publics de la semaine pour une liste d'entreprises, chacun avec sa source. Elle arrive avec la mise à jour faite au lancement de l'application.">
          Veille : aucune pour l'instant
        </PageTitle>
        {error && <Notice tone="error">{error}</Notice>}
      </>
    );
  }

  const followed = report.titres.filter((title) => title.suivi);
  const others = report.titres.filter((title) => !title.suivi);
  const news = followedNews(report.titres);
  const upcoming = followed
    .filter((title) => title.prochain_rendez_vous)
    .sort((a, b) => a.prochain_rendez_vous!.date.localeCompare(b.prochain_rendez_vous!.date));

  return (
    <>
      <PageTitle lead="Faits publics relevés par une IA, chacun avec sa source à vérifier. Ni prédiction, ni consigne d'achat ou de vente ; la Halalitude se vérifie à part.">
        Veille du {date(report.du)} au {date(report.au)} :{" "}
        {followed.length === 0
          ? "aucun titre suivi dans la liste"
          : news === 0
            ? "rien de notable sur les titres suivis"
            : `du nouveau sur ${plural(news, "titre suivi", "titres suivis")}`}
      </PageTitle>

      {error && (
        <div className="mb-6">
          <Notice tone="error">{error}</Notice>
        </div>
      )}

      {data.weeks.length > 1 && (
        <label className="mb-8 block text-sm">
          <span className="mr-3 text-muted">Semaine</span>
          <select
            value={report.semaine}
            onChange={(e) => load(e.target.value)}
            className={inputClass}
          >
            {data.weeks.map((week) => (
              <option key={week.semaine} value={week.semaine}>
                du {date(week.du)} au {date(week.au)}
              </option>
            ))}
          </select>
        </label>
      )}

      <Section
        title="Lignes détenues et cibles"
        note={
          data.uncovered.length > 0 &&
          `Hors de la liste couverte par la veille : ${data.uncovered.join(", ")}.`
        }
      >
        <Titles titles={followed} empty="Aucune ligne détenue ni cible ne figure dans la liste couverte." />
      </Section>

      {upcoming.length > 0 && (
        <Section title="Prochains rendez-vous">
          <TableWrap>
            <table className="data events">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Titre</th>
                  <th>Objet</th>
                  <th>Source</th>
                </tr>
              </thead>
              <tbody>
                {upcoming.map((title) => (
                  <tr key={title.isin}>
                    <td className="num">{date(title.prochain_rendez_vous!.date)}</td>
                    <td>{title.nom}</td>
                    <td>{title.prochain_rendez_vous!.objet}</td>
                    <td>
                      <SourceLink source={title.prochain_rendez_vous!.source} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        </Section>
      )}

      {report.macro.length > 0 && (
        <Section title="Contexte">
          <ul className="max-w-[80ch] space-y-3">
            {report.macro.map((point, position) => (
              <li key={position}>
                <span className="font-medium">{point.sujet}.</span> {point.texte}{" "}
                <span className="text-sm">
                  {point.sources.map((source, index) => (
                    <span key={index}>
                      {index > 0 && ", "}
                      <SourceLink source={source} />
                    </span>
                  ))}
                </span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {others.length > 0 && (
        <Section title="Reste de la liste">
          <details>
            <summary className="cursor-pointer text-accent">
              {plural(others.filter(hasNews).length, "autre titre", "autres titres")} avec du nouveau,
              sur {others.length}
            </summary>
            <div className="mt-6">
              <Titles titles={others} empty="" />
            </div>
          </details>
        </Section>
      )}
    </>
  );
}

function Titles({ titles, empty }: { titles: WatchTitle[]; empty: string }) {
  const withNews = titles.filter(hasNews);
  const quiet = titles.filter((title) => !hasNews(title));
  if (titles.length === 0) return <p className="text-muted">{empty}</p>;
  return (
    <>
      <div className="max-w-[80ch] space-y-6">
        {withNews.map((title) => (
          <article key={title.isin}>
            <h3 className="font-medium">
              {title.nom}
              {title.suivi && (
                <span className="ml-2 text-sm font-normal text-muted">{FOLLOWED[title.suivi]}</span>
              )}
            </h3>
            <ul className="mt-2 space-y-2">
              {[...title.faits]
                .sort((a, b) => a.date.localeCompare(b.date))
                .map((fact) => (
                  <li key={fact.date + fact.texte}>
                    <span className="num text-sm text-muted">{date(fact.date)}</span> {fact.texte}{" "}
                    <span className="text-sm">
                      <SourceLink source={fact.source} />
                    </span>
                  </li>
                ))}
              {title.a_regarder && (
                <li>
                  <span className="text-sm text-muted">À regarder</span> {title.a_regarder}
                </li>
              )}
            </ul>
          </article>
        ))}
      </div>
      {quiet.length > 0 && (
        <p className={`max-w-[80ch] text-sm text-muted ${withNews.length > 0 ? "mt-6" : ""}`}>
          Rien de notable : {quiet.map((title) => title.nom).join(", ")}.
        </p>
      )}
    </>
  );
}

/** A source opens in another tab: the watch is read here, checked there. */
function SourceLink({ source }: { source: WatchSource }) {
  return (
    <a
      className="text-accent underline underline-offset-4"
      href={source.url}
      target="_blank"
      rel="noreferrer"
    >
      {source.titre}
    </a>
  );
}

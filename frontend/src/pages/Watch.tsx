import { useEffect, useState } from "react";
import {
  api,
  type ReadingsRecord,
  type Watch as WatchData,
  type WatchReading,
  type WatchSource,
  type WatchTitle,
} from "../api";
import { Notice, PageTitle, Section, TableWrap, inputClass } from "../components/ui";
import { date, percent, plural, signedPercent } from "../format";

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

      {report.lecture && <Reading lecture={report.lecture} />}
      <Record />
    </>
  );
}

type Lecture = NonNullable<NonNullable<WatchData["report"]>["lecture"]>;
const LEANS = {
  hausse: "penche à la hausse",
  baisse: "penche à la baisse",
  partagée: "partagée",
} as const;

/** The interpretation of the week: said to be one, and kept apart from the facts. */
function Reading({ lecture }: { lecture: Lecture }) {
  const mine = lecture.secteurs.filter((sector) => sector.suivi);
  const others = lecture.secteurs.filter((sector) => !sector.suivi);
  return (
    <Section
      title="Lecture de la semaine"
      note="Interprétation rédigée par une IA à partir des faits ci-dessus. Ce n'est pas un conseil en investissement : la balance est une opinion argumentée, qui se trompera régulièrement. Elle ne justifie aucun ordre à elle seule."
    >
      <div className="max-w-[90ch] space-y-10">
        <ReadingBlock title="Marché" reading={lecture.marche} />
        {mine.map((sector) => (
          <ReadingBlock key={sector.secteur} title={sector.secteur} tag="secteur détenu ou ciblé" reading={sector} />
        ))}
        {others.length > 0 && (
          <details>
            <summary className="cursor-pointer text-accent">
              {plural(others.length, "autre secteur", "autres secteurs")}
            </summary>
            <div className="mt-6 space-y-10">
              {others.map((sector) => (
                <ReadingBlock key={sector.secteur} title={sector.secteur} reading={sector} />
              ))}
            </div>
          </details>
        )}
      </div>
    </Section>
  );
}

const VERDICTS = {
  juste: "juste",
  "à côté": "à côté",
  "non notée": "non notée : balance partagée",
  "en attente": "en attente",
  inconnu: "cours indisponible",
} as const;

/** What the past readings were worth, with the laziest forecast beside them. */
function Record() {
  const [record, setRecord] = useState<ReadingsRecord | null>(null);
  useEffect(() => {
    api
      .readingsRecord()
      .then(setRecord)
      .catch(() => setRecord(null));
  }, []);
  if (!record || record.rows.length === 0) return null;
  const { scored, right, always_up_right: naive, enough, minimum } = record.summary;
  return (
    <Section
      title="Ce que les lectures ont valu"
      note={`La balance du marché de chaque veille, face à ce que le ${record.benchmark} a fait en euros entre le vendredi de la veille et le vendredi suivant.`}
    >
      {record.error && (
        <div className="mb-4">
          <Notice tone="error">Cours de l'indice indisponibles : {record.error}.</Notice>
        </div>
      )}
      <p className="mb-4 max-w-[80ch]">
        {scored === 0 ? (
          "Aucune lecture n'a encore de verdict : le premier arrive après la clôture du vendredi qui suit la veille."
        ) : (
          <>
            {plural(right, "lecture juste", "lectures justes")} sur {scored}{" "}
            {scored > 1 ? "notées" : "notée"}. Sur les mêmes semaines, annoncer « hausse » à chaque
            fois aurait été juste {naive} fois.{" "}
            {enough
              ? `Soit ${percent(right / scored)} contre ${percent(naive / scored)}.`
              : `Pas de taux de réussite avant ${minimum} lectures notées : d'ici là, le hasard suffit à expliquer le score.`}
          </>
        )}
      </p>
      <TableWrap>
        <table className="data record">
          <thead>
            <tr>
              <th>Veille</th>
              <th>Balance annoncée</th>
              <th>Indice, semaine suivante</th>
              <th>Verdict</th>
            </tr>
          </thead>
          <tbody>
            {record.rows.map((row) => (
              <tr key={row.semaine}>
                <td>
                  du {date(row.du)} au {date(row.au)}
                </td>
                <td>
                  {LEANS[row.sens]}
                  <span className="text-muted">, confiance {row.confiance}</span>
                </td>
                <td className="num">
                  {row.variation == null ? (
                    <span className="text-muted">jusqu'au {date(row.jusqu_au)}</span>
                  ) : (
                    signedPercent(row.variation)
                  )}
                </td>
                <td>{VERDICTS[row.verdict]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableWrap>
    </Section>
  );
}

function ReadingBlock({ title, tag, reading }: { title: string; tag?: string; reading: WatchReading }) {
  return (
    <article>
      <h3 className="font-medium">
        {title}
        {tag && <span className="ml-2 text-sm font-normal text-muted">{tag}</span>}
      </h3>
      <p className="mt-1">
        Balance : <span className="font-medium">{LEANS[reading.balance.sens]}</span>
        <span className="text-muted">, confiance {reading.balance.confiance}.</span>{" "}
        {reading.balance.motif}
      </p>
      <div className="mt-4 grid gap-x-10 gap-y-4 md:grid-cols-2">
        <Arguments title="Ce qui pousse à la hausse" items={reading.hausse} />
        <Arguments title="Ce qui pousse à la baisse" items={reading.baisse} />
      </div>
      <div className="mt-4">
        <h4 className="text-sm text-muted">Ce qui trancherait</h4>
        <ul className="mt-1 space-y-1.5">
          {reading.signaux.map((signal) => (
            <li key={signal.texte}>
              {signal.date && <span className="num text-sm text-muted">{date(signal.date)} </span>}
              {signal.texte}
            </li>
          ))}
        </ul>
      </div>
    </article>
  );
}

function Arguments({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <h4 className="text-sm text-muted">{title}</h4>
      <ul className="mt-1 list-disc space-y-1.5 pl-5">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
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

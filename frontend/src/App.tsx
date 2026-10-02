import { useCallback, useEffect, useState } from "react";
import { api, type Report } from "./api";
import { Notice } from "./components/ui";
import { Activity } from "./pages/Activity";
import { Closed } from "./pages/Closed";
import { Data } from "./pages/Data";
import { Home } from "./pages/Home";
import { Portfolio } from "./pages/Portfolio";

const PAGES = [
  { id: "accueil", label: "Accueil" },
  { id: "portefeuille", label: "Portefeuille" },
  { id: "soldees", label: "Lignes soldées" },
  { id: "frais", label: "Frais et activité" },
  { id: "donnees", label: "Données" },
] as const;

type PageId = (typeof PAGES)[number]["id"];

const pageFromHash = (): PageId => {
  const id = window.location.hash.replace(/^#\/?/, "");
  return PAGES.some((p) => p.id === id) ? (id as PageId) : "accueil";
};

export default function App() {
  const [page, setPage] = useState<PageId>(pageFromHash);
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(() => {
    api
      .report()
      .then((data) => {
        setReport(data);
        setError(null);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(reload, [reload]);
  useEffect(() => {
    const onHash = () => setPage(pageFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const empty = report !== null && report.transactions === 0;
  const shown: PageId = empty ? "donnees" : page;

  return (
    <div className="mx-auto max-w-[1120px] px-5 pb-20 sm:px-8">
      <header className="flex flex-wrap items-baseline gap-x-8 gap-y-2 border-b border-line py-5">
        <span className="font-display text-lg">Cockpit TR</span>
        <nav aria-label="Pages" className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
          {PAGES.map((p) => (
            <a
              key={p.id}
              href={`#/${p.id}`}
              aria-current={shown === p.id ? "page" : undefined}
              className={
                shown === p.id
                  ? "border-b-2 border-accent pb-1 font-medium"
                  : "pb-1 text-muted hover:text-ink"
              }
            >
              {p.label}
            </a>
          ))}
        </nav>
      </header>

      <main className="pt-10">
        {error && (
          <Notice tone="error">
            Le serveur local ne répond pas ({error}). Relancer « cockpit serve », puis recharger la
            page.
          </Notice>
        )}
        {report && shown === "accueil" && <Home report={report} />}
        {report && shown === "portefeuille" && <Portfolio report={report} reload={reload} />}
        {report && shown === "soldees" && <Closed report={report} />}
        {report && shown === "frais" && <Activity report={report} />}
        {report && shown === "donnees" && <Data report={report} reload={reload} />}
      </main>
    </div>
  );
}

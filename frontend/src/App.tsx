import { useCallback, useEffect, useRef, useState } from "react";
import { api, type RefreshOutcome, type Report } from "./api";
import { Notice } from "./components/ui";
import { Activity } from "./pages/Activity";
import { Assistant } from "./pages/Assistant";
import { Closed } from "./pages/Closed";
import { HalalitudePage } from "./pages/Halalitude";
import { Data } from "./pages/Data";
import { Home } from "./pages/Home";
import { Journal } from "./pages/Journal";
import { Portfolio } from "./pages/Portfolio";
import { Reviews } from "./pages/Reviews";
import { Roadmap } from "./pages/Roadmap";
import { Rules } from "./pages/Rules";
import { Security } from "./pages/Security";
import { Tickets } from "./pages/Tickets";
import { Watch } from "./pages/Watch";

const PAGES = [
  { id: "accueil", label: "Accueil" },
  { id: "portefeuille", label: "Portefeuille" },
  { id: "feuille-de-route", label: "Feuille de route" },
  { id: "tickets", label: "Tickets" },
  { id: "regles", label: "Règles" },
  { id: "halalitude", label: "Halalitude" },
  { id: "veille", label: "Veille" },
  { id: "revues", label: "Revues" },
  { id: "assistant", label: "Assistant" },
  { id: "journal", label: "Journal" },
  { id: "soldees", label: "Lignes soldées" },
  { id: "frais", label: "Frais et activité" },
  { id: "donnees", label: "Données" },
] as const;

type PageId = (typeof PAGES)[number]["id"];
type Route = { page: PageId; isin?: string };

const REFRESH_EVERY = 120_000; // quotes are asked again every two minutes
const PAUSE_AFTER_REFUSAL = 900_000; // and left alone a quarter of an hour after a refusal

const routeFromHash = (): Route => {
  const path = window.location.hash.replace(/^#\/?/, "");
  const security = path.match(/^titre\/([A-Z0-9]{12})$/);
  if (security) return { page: "portefeuille", isin: security[1] };
  return { page: PAGES.some((p) => p.id === path) ? (path as PageId) : "accueil" };
};

export default function App() {
  const [route, setRoute] = useState<Route>(routeFromHash);
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<RefreshOutcome | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const pausedUntil = useRef(0);

  const reload = useCallback(() => {
    api
      .report()
      .then((data) => {
        setReport(data);
        setError(null);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      const result = await api.refreshQuotes();
      if (!result.busy) {
        setOutcome(result);
        if (result.refused || result.unreachable) {
          pausedUntil.current = Date.now() + PAUSE_AFTER_REFUSAL;
        }
      }
    } catch {
      /* the local server is down: the report request below says so */
    } finally {
      setRefreshing(false);
      reload();
    }
  }, [reload]);

  useEffect(reload, [reload]);
  useEffect(() => {
    refresh();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible" && Date.now() > pausedUntil.current) refresh();
    }, REFRESH_EVERY);
    return () => window.clearInterval(timer);
  }, [refresh]);
  useEffect(() => {
    const onHash = () => setRoute(routeFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const empty = report !== null && report.transactions === 0;
  const shown: PageId = empty ? "donnees" : route.page;
  const manualRefresh = () => {
    pausedUntil.current = 0;
    refresh();
  };

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
        {report && shown === "portefeuille" && route.isin && !empty && (
          <Security isin={route.isin} report={report} />
        )}
        {report && shown === "portefeuille" && !(route.isin && !empty) && (
          <Portfolio
            report={report}
            reload={reload}
            refresh={manualRefresh}
            refreshing={refreshing}
            outcome={outcome}
          />
        )}
        {report && shown === "feuille-de-route" && <Roadmap />}
        {report && shown === "tickets" && <Tickets report={report} />}
        {report && shown === "regles" && <Rules />}
        {report && shown === "halalitude" && <HalalitudePage reload={reload} />}
        {report && shown === "veille" && <Watch />}
        {report && shown === "revues" && <Reviews />}
        {report && shown === "assistant" && <Assistant />}
        {report && shown === "journal" && <Journal />}
        {report && shown === "soldees" && <Closed report={report} />}
        {report && shown === "frais" && <Activity report={report} />}
        {report && shown === "donnees" && <Data report={report} reload={reload} />}
      </main>
    </div>
  );
}

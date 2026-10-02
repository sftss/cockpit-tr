import { useEffect, useState } from "react";
import { api, type Allocation as AllocationData } from "../api";
import { euro, percent, plural } from "../format";
import { Section } from "./ui";

/**
 * How the portfolio is spread, one panel per dimension. Bars share one colour:
 * their length says the share, their label says which group it is.
 */
export function Allocation({ stamp }: { stamp: string | null }) {
  const [data, setData] = useState<AllocationData | null>(null);
  useEffect(() => {
    api
      .allocation()
      .then(setData)
      .catch(() => setData(null));
  }, [stamp]);
  if (!data || data.total <= 0) return null;

  return (
    <Section title="Répartition">
      <div className="grid gap-x-12 gap-y-10 lg:grid-cols-2">
        {data.dimensions.map((dimension) => {
          const largest = Math.max(...dimension.groups.map((group) => group.weight ?? 0), 0.0001);
          return (
            <section key={dimension.id} aria-label={dimension.title}>
              <h3 className="mb-3 font-medium">{dimension.title}</h3>
              <ul className="space-y-3">
                {dimension.groups.map((group) => (
                  <li key={group.label} className="text-sm">
                    <div className="mb-1 flex flex-wrap items-baseline justify-between gap-x-4">
                      <span>{group.label}</span>
                      <span className="text-muted">
                        <span className="num text-ink">{percent(group.weight)}</span> ·{" "}
                        <span className="num">{euro(group.amount)}</span> ·{" "}
                        {plural(group.lines, "ligne", "lignes")}
                      </span>
                    </div>
                    <span
                      className="block h-2 rounded-r-[4px] bg-[var(--chart-1)]"
                      style={{ width: `${Math.max(0.5, ((group.weight ?? 0) / largest) * 100)}%` }}
                    />
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
      </div>
      <p className="mt-6 max-w-[80ch] text-sm text-muted">
        Parts calculées sur {data.basis === "value" ? "la valeur" : "le prix de revient, faute de cours pour chaque ligne"}
        . Pays du siège social et secteur (nomenclature GICS, à titre indicatif) viennent de la liste
        publique des entreprises ; un fonds compte pour un seul bloc, sans regarder ce qu'il détient.
        {data.unclassified.length > 0 && ` Hors liste, donc non classé : ${data.unclassified.join(", ")}.`}
      </p>
    </Section>
  );
}

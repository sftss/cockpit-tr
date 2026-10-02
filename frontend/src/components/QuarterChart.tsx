import { useState } from "react";
import type { Quarter } from "../api";
import { euro, plural, quarterName } from "../format";

const HEIGHT = 150;

/**
 * Manual orders per quarter: one series, so one colour and no legend.
 * Only the highest bar and the latest quarter carry a number; the others
 * answer on hover or keyboard focus. The same figures are in a table on
 * the "Frais et activité" page.
 */
export function QuarterChart({ quarters, current }: { quarters: Quarter[]; current: string }) {
  const [active, setActive] = useState<string | null>(null);
  const max = Math.max(1, ...quarters.map((q) => q.manual_orders));
  const peak = quarters.reduce((a, b) => (b.manual_orders > a.manual_orders ? b : a), quarters[0]);
  const shown = quarters.find((q) => q.quarter === active);

  return (
    <figure>
      <div
        className="flex items-end gap-[2px] border-b border-line"
        style={{ height: HEIGHT + 24 }}
        onMouseLeave={() => setActive(null)}
      >
        {quarters.map((q) => {
          const labelled = q.quarter === peak.quarter || q.quarter === current;
          const height = Math.round((q.manual_orders / max) * HEIGHT);
          return (
            <button
              key={q.quarter}
              type="button"
              aria-label={`${quarterName(q.quarter)} : ${plural(q.manual_orders, "ordre manuel", "ordres manuels")}, ${euro(q.order_fees)} de frais d'ordre`}
              onMouseEnter={() => setActive(q.quarter)}
              onFocus={() => setActive(q.quarter)}
              onBlur={() => setActive(null)}
              className="group flex h-full min-w-0 flex-1 flex-col items-center justify-end"
            >
              <span className={`num mb-1 text-xs ${labelled || active === q.quarter ? "" : "invisible"}`}>
                {q.manual_orders}
              </span>
              <span
                className={`w-full max-w-10 rounded-t-[4px] ${
                  q.quarter === current ? "bg-accent" : "bg-accent/45"
                } group-hover:bg-accent group-focus-visible:bg-accent`}
                style={{ height: Math.max(height, q.manual_orders ? 2 : 0) }}
              />
            </button>
          );
        })}
      </div>
      <div className="mt-1 flex gap-[2px] text-xs text-muted" aria-hidden="true">
        {quarters.map((q) => (
          <span key={q.quarter} className="min-w-0 flex-1 text-center">
            {q.quarter.endsWith("T1") || q === quarters[0] ? q.quarter.slice(0, 4) : ""}
          </span>
        ))}
      </div>
      <figcaption className="mt-2 min-h-5 text-sm text-muted" aria-live="polite">
        {shown
          ? `${quarterName(shown.quarter)} : ${plural(shown.manual_orders, "ordre manuel", "ordres manuels")}, ${euro(shown.order_fees)} de frais d'ordre`
          : "Une barre par trimestre. Survoler une barre pour le détail."}
      </figcaption>
    </figure>
  );
}

import type { Zoya } from "../api";
import { date } from "../format";

const NAMES = { conforme: "conforme", non_conforme: "non conforme", douteux: "douteux" } as const;

/** True when the status deserves a look: missing, too old, or not compliant. */
export const zoyaNeedsAttention = (zoya: Zoya | null) =>
  !zoya || zoya.state !== "a_jour" || zoya.status !== "conforme";

/** The compliance status in one line, as it was read by hand and when. */
export function ZoyaLabel({ zoya }: { zoya: Zoya | null }) {
  if (!zoya || zoya.state === "non_renseigne" || !zoya.status) {
    return <span className="text-alert">Zoya non renseigné</span>;
  }
  const stale = zoya.state === "a_reverifier";
  return (
    <span className={zoyaNeedsAttention(zoya) ? "text-alert" : undefined}>
      Zoya {NAMES[zoya.status]}, vu le {date(zoya.checked_on)}
      {stale && ", à revérifier"}
    </span>
  );
}

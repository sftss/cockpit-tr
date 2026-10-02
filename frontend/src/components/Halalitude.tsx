import type { Halalitude } from "../api";
import { date } from "../format";

const NAMES = { conforme: "halal", douteux: "douteux", non_conforme: "haram" } as const;

/** True when the status deserves a look: missing, too old, or not halal. */
export const needsAttention = (status: Halalitude | null) =>
  !status || status.state !== "a_jour" || status.status !== "conforme";

/** The status in one line, as it was read by hand in the screeners, and when. */
export function HalalitudeLabel({ status }: { status: Halalitude | null }) {
  if (!status || status.state === "non_renseigne" || !status.status) {
    return <span className="text-alert">Halalitude non renseignée</span>;
  }
  const stale = status.state === "a_reverifier";
  return (
    <span className={needsAttention(status) ? "text-alert" : undefined}>
      Halalitude : {NAMES[status.status]}, relevée le {date(status.checked_on)}
      {stale && ", à revérifier"}
    </span>
  );
}

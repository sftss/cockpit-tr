const eur = new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR" });
const pct1 = new Intl.NumberFormat("fr-FR", {
  style: "percent",
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});
const qty4 = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 4 });
const day = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short", year: "numeric" });

export const DASH = "—";

export const euro = (value: number | null | undefined) =>
  value == null ? DASH : eur.format(value);

/** Signed amount: a result, not a balance. */
export const signedEuro = (value: number | null | undefined) =>
  value == null ? DASH : (value > 0 ? "+" : "") + eur.format(value);

export const percent = (value: number | null | undefined) =>
  value == null ? DASH : pct1.format(value);

export const signedPercent = (value: number | null | undefined) =>
  value == null ? DASH : (value > 0 ? "+" : "") + pct1.format(value);

export const quantity = (value: number) => qty4.format(value);

export const date = (iso: string | null | undefined) =>
  iso ? day.format(new Date(iso.length === 10 ? `${iso}T12:00:00` : iso)) : DASH;

export const accountName = (id: string) =>
  ({ CTO: "Compte-titres", PEA: "PEA" })[id] ?? id;

/** "2026-T3" -> "T3 2026" */
export const quarterName = (id: string) => {
  const [year, q] = id.split("-");
  return `${q} ${year}`;
};

export const quarterOf = (d: Date) => `${d.getFullYear()}-T${Math.floor(d.getMonth() / 3) + 1}`;

export const previousQuarter = (id: string) => {
  const [year, q] = id.split("-T").map(Number);
  return q === 1 ? `${year - 1}-T4` : `${year}-T${q - 1}`;
};

export const plural = (n: number, one: string, many: string) => `${n} ${n > 1 ? many : one}`;

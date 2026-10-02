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

const hourMinute = new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit" });

export const clock = (iso: string | null | undefined) =>
  iso ? hourMinute.format(new Date(iso)) : DASH;

const currencyFormats = new Map<string, Intl.NumberFormat>();

/** An amount in any currency, e.g. a price in dollars. */
export const amount = (value: number | null | undefined, currency: string) => {
  if (value == null) return DASH;
  let format = currencyFormats.get(currency);
  if (!format) {
    try {
      format = new Intl.NumberFormat("fr-FR", { style: "currency", currency });
    } catch {
      format = new Intl.NumberFormat("fr-FR", { minimumFractionDigits: 2 });
    }
    currencyFormats.set(currency, format);
  }
  return format.format(value);
};

export const delayLabel = (minutes: number | null | undefined) =>
  minutes == null ? "délai non connu" : minutes === 0 ? "temps réel" : `différé de ${minutes} min`;

const eurRound = new Intl.NumberFormat("fr-FR", {
  style: "currency",
  currency: "EUR",
  maximumFractionDigits: 0,
});

/** Whole euros, for chart axes where cents are noise. */
export const euroRound = (value: number) => eurRound.format(value);

/** Today as an ISO day, in local time: the default of every date field. */
export const today = () => {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
};

const plain = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 2 });

/** A number as a person writes it: 4, 100, 2,5. */
export const number = (value: number) => plain.format(value);

const gram = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 3 });

export const grams = (value: number) => `${gram.format(value)} g`;

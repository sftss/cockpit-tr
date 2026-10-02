export type Account = {
  account: string;
  open_lines: number;
  closed_lines: number;
  net_invested: number;
  open_cost: number;
  value: number | null;
  priced_lines: number;
  latent: number | null;
  performance: number | null;
  closed_net: number;
  order_fees: number;
  dividends: number;
  cash_estimate: number;
};

export type Position = {
  account: string;
  isin: string;
  name: string;
  asset_class: string;
  shares: number;
  cost: number;
  average_cost: number | null;
  price: number | null;
  price_date: string | null;
  value: number | null;
  latent: number | null;
  latent_pct: number | null;
  weight: number | null;
  weight_basis: "value" | "cost";
  fees: number;
  realized: number;
  dividends: number;
  first_buy: string | null;
  quote: Quote | null;
  spark: number[];
};

export type Quote = {
  price: number;
  currency: string;
  price_eur: number;
  change: number | null;
  market_time: string | null;
  exchange: string | null;
  delay_minutes: number | null;
  fetched_at: string;
};

export type RefreshOutcome = {
  busy: boolean;
  updated: number;
  skipped: number;
  errors: string[];
  refused: boolean;
  unreachable: boolean;
};

export type Instrument = {
  isin: string;
  name: string;
  held: boolean;
  symbol: string | null;
  exchange: string | null;
  currency: string | null;
  status: "ok" | "manuel" | "introuvable" | null;
  delay_minutes: number | null;
  last_quote: string | null;
  price_days: number;
};

export type ChartData = {
  isin: string;
  symbol: string;
  range: string;
  currency: string;
  exchange: string;
  delay_minutes: number | null;
  intraday: boolean;
  points: { time: number; value: number }[];
};

export type ValuePoint = {
  date: string;
  value: number;
  invested: number;
  at_cost: number;
  accounts: Record<string, number>;
};

export type ValueHistory = { points: ValuePoint[]; unpriced: string[] };

export type ClosedLine = {
  account: string;
  isin: string;
  name: string;
  bought: number;
  sold: number;
  gross: number;
  fees: number;
  taxes: number;
  net: number;
  net_pct: number | null;
  first_buy: string | null;
  closed_on: string | null;
  holding_days: number | null;
};

export type Quarter = {
  quarter: string;
  manual_orders: number;
  trades: number;
  order_fees: number;
  deposit_fees: number;
};

export type Report = {
  period: { from: string; to: string } | null;
  transactions: number;
  last_import: string | null;
  accounts: Account[];
  positions: Position[];
  closed: ClosedLine[];
  closed_summary: {
    count: number;
    winners: number;
    bought: number;
    gross: number;
    fees: number;
    taxes: number;
    net: number;
    net_pct: number | null;
  };
  fees: {
    orders: Record<string, number>;
    deposits: number;
    other: number;
    total: number;
    share_of_capital: number | null;
  };
  flows: {
    deposits: number;
    card_spending: number;
    capital_brought_in: number;
    dividends: number;
    interest: number;
    income_taxes: number;
  };
  quarters: Quarter[];
  manual_orders: number;
  anomalies: string[];
};

export type ImportReport = {
  total: number;
  inserted: number;
  already_present: number;
  rejected: string[];
  unknown_types: Record<string, number>;
  date_min: string | null;
  date_max: string | null;
};

export type SnapshotSummary = {
  id: number;
  taken_at: string;
  label: string | null;
  positions: number;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    let detail = `Erreur ${response.status}`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* keep the status text */
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  report: () => request<Report>("/api/report"),
  importCsv: (text: string) =>
    request<ImportReport>("/api/import/csv", {
      method: "POST",
      headers: { "Content-Type": "text/csv" },
      body: text,
    }),
  setPrice: (isin: string, price: string) => request(`/api/prices/${isin}`, json("PUT", { price })),
  refreshQuotes: () => request<RefreshOutcome>("/api/market/refresh", { method: "POST" }),
  loadHistory: () => request<RefreshOutcome>("/api/market/history", { method: "POST" }),
  instruments: () => request<Instrument[]>("/api/market/instruments"),
  setSymbol: (isin: string, symbol: string) =>
    request(`/api/market/instruments/${isin}`, json("PUT", { symbol })),
  chart: (isin: string, range: string) =>
    request<ChartData>(`/api/market/chart/${isin}?range=${encodeURIComponent(range)}`),
  valueHistory: () => request<ValueHistory>("/api/portfolio/history"),
  snapshots: () => request<SnapshotSummary[]>("/api/snapshots"),
  takeSnapshot: (label: string) =>
    request<{ id: number }>("/api/snapshots", json("POST", { label: label || null })),
};

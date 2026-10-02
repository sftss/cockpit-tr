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
  halalitude: Halalitude;
  weight_total: number | null;
};

export type HalalitudeStatus = "conforme" | "non_conforme" | "douteux";

/** Compliance status as read by hand in the screening apps, and how fresh it is. */
export type Halalitude = {
  status: HalalitudeStatus | null;
  checked_on: string | null;
  note: string | null;
  age_days: number | null;
  due_on: string | null;
  state: "non_renseigne" | "a_jour" | "a_reverifier";
};

export type ComplianceItem = Halalitude & {
  isin: string;
  name: string;
  group: "detenu" | "cible" | "autre";
  checks: number;
};

export type Compliance = {
  validity_days: number;
  statuses: Record<HalalitudeStatus, string>;
  items: ComplianceItem[];
  summary: { held: number; missing: number; stale: number; not_compliant: number };
};

export type RuleKind = {
  kind: string;
  label: string;
  unit: string;
  bound: "max" | "min";
  help: string;
  per_account?: boolean;
};

export type Rule = {
  id: number;
  kind: string;
  account: string | null;
  value: number;
  valid_from: string;
  valid_to: string | null;
  note: string | null;
};

export type RuleLine = {
  kind: string;
  label: string;
  unit: string;
  bound: "max" | "min";
  account: string | null;
  count: number;
  limit: number | null;
  breaches: number;
  portfolio_value?: number | null;
  minimums?: { account: string | null; value: number }[];
  lines?: { name: string; account: string; weight: number }[];
};

export type Deviation = {
  transaction_id: string;
  date: string;
  quarter: string;
  account: string;
  type: string;
  name: string;
  isin: string | null;
  amount: number;
  fee: number;
  breaches: { kind: string; label: string; detail: string }[];
  reason: string | null;
};

export type RulesState = {
  quarter: string;
  kinds: RuleKind[];
  rules: Rule[];
  current: RuleLine[];
  deviations: Deviation[];
  pending: number;
  has_rules: boolean;
};

export type RoadmapStatus = "idee" | "prevu" | "execute" | "abandonne";

export type RoadmapItem = {
  id: number;
  name: string;
  isin: string | null;
  account: string | null;
  amount: number | null;
  entry_condition: string | null;
  entry_price: number | null;
  thesis: string | null;
  status: RoadmapStatus;
  symbol: string | null;
  last_price: number | null;
  last_price_at: string | null;
  reached: boolean;
  proposed_by: "assistant" | null;
  halalitude: Halalitude | null;
};

export type RoadmapDraft = {
  name: string;
  isin: string;
  account: string;
  amount: string;
  entry_condition: string;
  entry_price: string;
  thesis: string;
  status: RoadmapStatus;
  symbol: string;
};

export type Roadmap = { statuses: Record<RoadmapStatus, string>; items: RoadmapItem[] };

export type GoldLot = {
  id: number;
  label: string;
  grams: number;
  cost: number | null;
  acquired_on: string | null;
  note: string | null;
  value: number | null;
  latent: number | null;
};

export type Gold = {
  lots: GoldLot[];
  grams: number;
  cost: number | null;
  value: number | null;
  latent: number | null;
  latent_pct: number | null;
  eur_per_gram: number | null;
  price_date: string | null;
  fetched_at: string | null;
};

export type GoldDraft = { label: string; grams: string; cost: string; acquired_on: string; note: string };

export type SettingsImport = {
  rules_added: number;
  rules_present: number;
  roadmap_added: number;
  roadmap_present: number;
  context_added: number;
  context_present: number;
};

export type MonthUsage = {
  month: string;
  calls: number;
  tokens_in: number;
  tokens_out: number;
  web_searches: number;
  cost_usd: number;
  cost_eur: number | null;
  budget_eur: number;
  share_of_budget: number;
};

export type AssistantStatus = {
  configured: boolean;
  key_source: "coffre" | "environnement" | null;
  models: { id: string; label: string }[];
  default_model: string;
  month: MonthUsage;
};

export type AssistantTurn = {
  role: "assistant";
  text: string;
  at: string;
  model: string | null;
  activity: { label: string; writes: boolean }[];
  sources: { url: string; title: string | null }[];
  usage: { tokens_in: number; tokens_out: number; web_searches: number; cost_usd: number };
};

export type Turn = { role: "user"; text: string; at: string } | AssistantTurn;

export type Conversation = {
  id: number;
  title: string;
  model: string;
  updated_at: string;
  turns: Turn[];
};

export type ConversationSummary = {
  id: number;
  title: string;
  model: string;
  updated_at: string;
  messages: number;
};

/** What the server sends while an answer is being written. */
export type ChatEvent =
  | { type: "text"; text: string }
  | { type: "activity"; label: string; writes?: boolean }
  | { type: "error"; message: string; kind?: string }
  | { type: "done"; conversation: Conversation | null; month: MonthUsage };

export type ContextDocument = { id: number; title: string; content: string; updated_at: string };

export type JournalEntry = {
  id: number;
  decided_on: string;
  title: string;
  body: string | null;
  author: "moi" | "assistant";
};

export type JournalDraft = { title: string; body: string; decided_on: string };

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

export type Candidate = {
  symbol: string;
  name: string;
  exchange: string;
  kind: string;
  price: number | null;
  currency: string | null;
  price_eur: number | null;
};

export type Candidates = {
  isin: string;
  name: string;
  query: string;
  by: "isin" | "nom";
  candidates: Candidate[];
  last_trade: { date: string; price: number } | null;
};

/** One bar: the close always, the rest of the bar when the source gives it. */
export type Bar = {
  time: number;
  value: number;
  open: number | null;
  high: number | null;
  low: number | null;
  volume: number | null;
};

export type Trade = {
  datetime: string;
  date: string;
  account: string;
  side: "achat" | "vente";
  shares: number;
  price: number | null;
  amount: number;
  fee: number;
};

export type ChartData = {
  isin: string;
  symbol: string;
  range: string;
  /** Currency of the figures: euros when a conversion was asked, else the quotation's. */
  currency: string;
  native_currency: string;
  exchange: string;
  delay_minutes: number | null;
  intraday: boolean;
  points: Bar[];
  averages: { window: number; label: string; points: { time: number; value: number }[] }[];
  /** The user's own trades, each on the bar of its day. */
  trades: (Trade & { time: number })[];
};

export type SecurityStats = {
  currency: string;
  as_of: string;
  price: number;
  previous_close: number | null;
  open: number | null;
  day_low: number | null;
  day_high: number | null;
  year_low: number;
  year_high: number;
  volume: number | null;
  average_volume: number | null;
  changes: { label: string; change: number | null }[];
};

export type SecurityData = {
  isin: string;
  name: string;
  asset_class: string | null;
  held: boolean;
  trades: Trade[];
  stats: SecurityStats | null;
  stats_error: string | null;
};

export type Performance = {
  benchmarks: { id: string; label: string }[];
  benchmark: { id: string; label: string };
  /** Portfolio: chained daily changes from 1. Benchmark: its price, null before the first. */
  points: { date: string; portfolio: number; benchmark: number | null }[];
  priced: boolean;
  error: string | null;
};

export type Allocation = {
  basis: "value" | "cost";
  total: number;
  dimensions: {
    id: string;
    title: string;
    groups: { label: string; amount: number; weight: number | null; lines: number }[];
  }[];
  unclassified: string[];
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
  total: { basis: "value" | "cost"; amount: number; lines: number };
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

export type WatchSource = { titre: string; url: string };

export type WatchTitle = {
  nom: string;
  isin: string;
  faits: { date: string; texte: string; source: WatchSource }[];
  prochain_rendez_vous: { date: string; objet: string; source: WatchSource } | null;
  a_regarder: string | null;
  /** Held line, target of the roadmap, or neither: decided on this machine. */
  suivi: "ligne" | "cible" | null;
};

export type WatchWeek = { semaine: string; du: string; au: string };

export type Watch = {
  weeks: WatchWeek[];
  report:
    | (WatchWeek & {
        macro: { sujet: string; texte: string; sources: WatchSource[] }[];
        titres: WatchTitle[];
      })
    | null;
  /** Held companies and targets the watch does not cover. */
  uncovered: string[];
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

/** Send a message and hand each event to `onEvent` as the answer is written. */
async function sendMessage(
  conversationId: number,
  body: { text: string; web_search: boolean; model: string },
  onEvent: (event: ChatEvent) => void,
): Promise<void> {
  const response = await fetch(`/api/assistant/conversations/${conversationId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok || !response.body) {
    let detail = `Erreur ${response.status}`;
    try {
      const failure = await response.json();
      if (typeof failure.detail === "string") detail = failure.detail;
    } catch {
      /* keep the status text */
    }
    throw new Error(detail);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // Events are separated by a blank line; the last piece may be incomplete.
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      const line = part.split("\n").find((l) => l.startsWith("data: "));
      if (line) onEvent(JSON.parse(line.slice(6)) as ChatEvent);
    }
  }
}

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
  candidates: (isin: string) =>
    request<Candidates>(`/api/market/instruments/${isin}/candidates`),
  chart: (isin: string, range: string, inEuros: boolean) =>
    request<ChartData>(
      `/api/market/chart/${isin}?range=${encodeURIComponent(range)}${inEuros ? "&devise=eur" : ""}`,
    ),
  security: (isin: string, inEuros: boolean) =>
    request<SecurityData>(`/api/securities/${isin}${inEuros ? "?devise=eur" : ""}`),
  performance: (benchmark?: string) =>
    request<Performance>(
      `/api/portfolio/performance${benchmark ? `?indice=${encodeURIComponent(benchmark)}` : ""}`,
    ),
  allocation: () => request<Allocation>("/api/portfolio/allocation"),
  valueHistory: () => request<ValueHistory>("/api/portfolio/history"),
  snapshots: () => request<SnapshotSummary[]>("/api/snapshots"),
  takeSnapshot: (label: string) =>
    request<{ id: number }>("/api/snapshots", json("POST", { label: label || null })),

  rules: () => request<RulesState>("/api/rules"),
  setRule: (rule: { kind: string; value: string; valid_from: string; account: string | null }) =>
    request<{ id: number }>("/api/rules", json("POST", rule)),
  deleteRule: (id: number) => request(`/api/rules/${id}`, { method: "DELETE" }),
  setReason: (transactionId: string, reason: string) =>
    request(`/api/deviations/${encodeURIComponent(transactionId)}`, json("PUT", { reason })),

  compliance: () => request<Compliance>("/api/compliance"),
  recordCompliance: (entry: { isin: string; status: string; checked_on: string; note: string }) =>
    request("/api/compliance", json("POST", entry)),

  roadmap: () => request<Roadmap>("/api/roadmap"),
  addRoadmapItem: (item: RoadmapDraft) => request<{ id: number }>("/api/roadmap", json("POST", item)),
  updateRoadmapItem: (id: number, item: RoadmapDraft) =>
    request(`/api/roadmap/${id}`, json("PUT", item)),
  deleteRoadmapItem: (id: number) => request(`/api/roadmap/${id}`, { method: "DELETE" }),
  refreshRoadmapPrices: () =>
    request<{ updated: number; errors: string[]; refused: boolean; unreachable: boolean }>(
      "/api/roadmap/prices",
      { method: "POST" },
    ),

  gold: () => request<Gold>("/api/gold"),
  addGoldLot: (lot: GoldDraft) => request<{ id: number }>("/api/gold/lots", json("POST", lot)),
  updateGoldLot: (id: number, lot: GoldDraft) => request(`/api/gold/lots/${id}`, json("PUT", lot)),
  deleteGoldLot: (id: number) => request(`/api/gold/lots/${id}`, { method: "DELETE" }),
  refreshGoldPrice: () => request<Gold>("/api/gold/price", { method: "POST" }),

  assistantStatus: () => request<AssistantStatus>("/api/assistant/status"),
  saveKey: (key: string) => request<AssistantStatus>("/api/assistant/key", json("PUT", { key })),
  deleteKey: () => request<AssistantStatus>("/api/assistant/key", { method: "DELETE" }),
  saveAssistantSettings: (settings: { model?: string; budget_eur?: string }) =>
    request<AssistantStatus>("/api/assistant/settings", json("PUT", settings)),
  contextDocuments: () => request<ContextDocument[]>("/api/assistant/context"),
  saveContextDocument: (title: string, content: string) =>
    request<{ id: number }>("/api/assistant/context", json("PUT", { title, content })),
  deleteContextDocument: (id: number) =>
    request(`/api/assistant/context/${id}`, { method: "DELETE" }),
  conversations: () => request<ConversationSummary[]>("/api/assistant/conversations"),
  conversation: (id: number) => request<Conversation>(`/api/assistant/conversations/${id}`),
  createConversation: (model: string) =>
    request<Conversation>("/api/assistant/conversations", json("POST", { model })),
  deleteConversation: (id: number) =>
    request(`/api/assistant/conversations/${id}`, { method: "DELETE" }),
  sendMessage,

  journal: () => request<JournalEntry[]>("/api/journal"),
  addJournalEntry: (entry: JournalDraft) => request<{ id: number }>("/api/journal", json("POST", entry)),
  updateJournalEntry: (id: number, entry: JournalDraft) =>
    request(`/api/journal/${id}`, json("PUT", entry)),
  deleteJournalEntry: (id: number) => request(`/api/journal/${id}`, { method: "DELETE" }),

  watch: (week?: string) =>
    request<Watch>(`/api/veille${week ? `?semaine=${encodeURIComponent(week)}` : ""}`),

  importSettings: (text: string) =>
    request<SettingsImport>("/api/settings/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: text,
    }),
};

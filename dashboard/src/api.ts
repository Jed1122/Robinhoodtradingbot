export type Row = Record<string, unknown>;
export type Action = "pause" | "resume_research" | "kill";
export interface StockWorker {
  exported_at: string | null;
  last_claim_at: string | null;
  last_result_at: string | null;
  phase: "discovery" | "enrichment" | null;
  status:
    | "never_run"
    | "pending"
    | "succeeded"
    | "blocked"
    | "failed"
    | "cancelled"
    | "unavailable";
  reason: string | null;
  pending_claims: number | null;
  reserved_today: number | null;
  daily_limit: number | null;
  remaining_calls: number | null;
  next_eligible_at: string | null;
  discovery_as_of: string | null;
  enrichment_as_of: string | null;
  control_scope: "separate";
  qualified: false;
  live_enabled: false;
}
const stockMetricLabels = {
  roe: "Return on equity",
  net_margin: "Net margin",
  annual_eps_growth: "Annual EPS growth",
  quarterly_revenue_growth: "Quarterly revenue growth",
  earnings_yield: "Earnings yield",
  fcf_yield: "Free cash flow yield",
} as const;
export { stockMetricLabels };
export type StockOpportunity = Row & {
  symbol: string;
  strategy: "fundamental_screen";
  status: "unqualified_research";
  reason: string;
  research_priority_score: string;
  available_at: string;
  metrics: Record<keyof typeof stockMetricLabels, string | null>;
  gaps: string[];
  dossier_as_of: string | null;
};
export interface Snapshot {
  mode: "paper";
  live_enabled: false;
  generated_at?: string;
  portfolio: {
    starting_capital: string;
    equity: string | null;
    cash: string;
    buying_power: string;
    reserved_cash: string;
    tax_reserve: string;
    realized_gain: string;
    unrealized_gain: string | null;
    drawdown_pct: string | null;
    valuation_status?: string;
    allocations: {
      long_term: string | null;
      tactical: string | null;
      reserve: string;
    };
    positions: Row[];
    orders: Row[];
    lots: Row[];
  };
  research: {
    regime: string | Row;
    opportunities: Row[];
    sources: Row[];
    strategy_status: Row[];
    comparisons: Row[];
    limitations: string[];
    stock_worker?: StockWorker;
  };
  safety: {
    paused: boolean;
    kill_switch: boolean;
    live_enabled: false;
    paper_period_required: boolean;
    readiness: Row[];
    authorization_status: "not_authorized";
  };
  costs: {
    monthly_usd: string;
    annual_pct_of_starting_capital: string;
    additional_budget_usd: number | string;
  };
  jobs: Row[];
  reports: Row[];
}
const isObject = (value: unknown): value is Row =>
  !!value && typeof value === "object" && !Array.isArray(value);
const decimalString = (value: unknown): value is string =>
  typeof value === "string" &&
  value.length <= 128 &&
  /^-?\d+(\.\d+)?$/.test(value) &&
  Number.isFinite(Number(value));
const researchScore = (value: unknown): value is string =>
  decimalString(value) &&
  /^(?:\d{1,2}(?:\.\d+)?|100(?:\.0+)?)$/.test(value.replace(/^0+(?=\d)/, ""));
const utcTimestamp = (value: unknown): value is string => {
  if (
    typeof value !== "string" ||
    !/^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])T([01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(
      value,
    )
  )
    return false;
  const parsed = Date.parse(value);
  return (
    Number.isFinite(parsed) &&
    new Date(parsed).toISOString().slice(0, 19) === value.slice(0, 19)
  );
};
export function isStockOpportunity(value: Row): value is StockOpportunity {
  return (
    typeof value.symbol === "string" &&
    /^[A-Z][A-Z0-9./-]{0,31}$/.test(value.symbol) &&
    value.strategy === "fundamental_screen" &&
    value.status === "unqualified_research" &&
    typeof value.reason === "string" &&
    value.reason.length > 0 &&
    value.reason.length <= 512 &&
    researchScore(value.research_priority_score) &&
    utcTimestamp(value.available_at) &&
    (value.dossier_as_of === null || utcTimestamp(value.dossier_as_of)) &&
    isObject(value.metrics) &&
    Object.keys(stockMetricLabels).every((key) => {
      const metric = (value.metrics as Row)[key];
      return metric === null || decimalString(metric);
    }) &&
    Array.isArray(value.gaps) &&
    value.gaps.length <= 64 &&
    value.gaps.every(
      (gap) => typeof gap === "string" && gap.length > 0 && gap.length <= 256,
    )
  );
}
function validStockWorker(value: unknown): value is StockWorker {
  if (
    !isObject(value) ||
    value.control_scope !== "separate" ||
    value.qualified !== false ||
    value.live_enabled !== false ||
    ![
      "never_run",
      "pending",
      "succeeded",
      "blocked",
      "failed",
      "cancelled",
      "unavailable",
    ].includes(value.status as string) ||
    ![null, "discovery", "enrichment"].includes(value.phase as string | null) ||
    !(
      value.reason === null ||
      (typeof value.reason === "string" &&
        /^[a-z][a-z0-9_]{0,127}$/.test(value.reason))
    )
  )
    return false;
  if (
    ![
      "exported_at",
      "last_claim_at",
      "last_result_at",
      "next_eligible_at",
      "discovery_as_of",
      "enrichment_as_of",
    ].every((key) => value[key] === null || utcTimestamp(value[key]))
  )
    return false;
  return [
    "pending_claims",
    "reserved_today",
    "daily_limit",
    "remaining_calls",
  ].every((key) => {
    const count = value[key];
    if (count === null) return value.status === "unavailable";
    return (
      typeof count === "number" &&
      Number.isSafeInteger(count) &&
      count >= (key === "daily_limit" ? 1 : 0) &&
      (key === "pending_claims" || count <= 1024)
    );
  });
}
export function validateSnapshot(value: unknown): Snapshot {
  if (
    !isObject(value) ||
    value.mode !== "paper" ||
    value.live_enabled !== false ||
    !isObject(value.safety) ||
    value.safety.live_enabled !== false ||
    value.safety.authorization_status !== "not_authorized" ||
    typeof value.safety.paused !== "boolean" ||
    typeof value.safety.kill_switch !== "boolean" ||
    typeof value.safety.paper_period_required !== "boolean" ||
    !isObject(value.portfolio) ||
    !isObject(value.research) ||
    !isObject(value.costs)
  )
    throw new Error(
      "Unsupported or invalid snapshot. Controls are unavailable.",
    );
  const { portfolio, research, safety, costs } = value;
  for (const key of [
    "starting_capital",
    "cash",
    "buying_power",
    "reserved_cash",
    "tax_reserve",
    "realized_gain",
  ])
    if (
      typeof portfolio[key] !== "string" ||
      !/^-?\d+(\.\d+)?$/.test(portfolio[key] as string) ||
      !Number.isFinite(Number(portfolio[key]))
    )
      throw new Error("Invalid portfolio data. Controls are unavailable.");
  for (const key of ["equity", "unrealized_gain", "drawdown_pct"]) {
    const field = portfolio[key];
    if (
      field !== null &&
      (typeof field !== "string" ||
        !/^-?\d+(\.\d+)?$/.test(field) ||
        !Number.isFinite(Number(field)))
    ) {
      throw new Error("Invalid valuation data. Controls are unavailable.");
    }
  }
  if (
    portfolio.valuation_status !== undefined &&
    typeof portfolio.valuation_status !== "string"
  ) {
    throw new Error("Invalid valuation status. Controls are unavailable.");
  }
  if (
    !isObject(portfolio.allocations) ||
    !["long_term", "tactical", "reserve"].every(
      (key) =>
        (key !== "reserve" && (portfolio.allocations as Row)[key] === null) ||
        (typeof (portfolio.allocations as Row)[key] === "string" &&
          /^\d+(\.\d+)?$/.test((portfolio.allocations as Row)[key] as string) &&
          Number.isFinite(Number((portfolio.allocations as Row)[key]))),
    )
  )
    throw new Error("Invalid allocation data. Controls are unavailable.");
  for (const [object, keys] of [
    [portfolio, ["positions", "orders", "lots"]],
    [research, ["opportunities", "sources", "strategy_status", "comparisons"]],
    [safety, ["readiness"]],
    [value, ["jobs", "reports"]],
  ] as [Row, string[]][])
    for (const key of keys)
      if (
        !Array.isArray(object[key]) ||
        !(object[key] as unknown[]).every(isObject)
      )
        throw new Error(
          "Invalid snapshot collection. Controls are unavailable.",
        );
  if (
    !Array.isArray(research.limitations) ||
    !research.limitations.every((v) => typeof v === "string") ||
    !(typeof research.regime === "string" || isObject(research.regime)) ||
    !["monthly_usd", "annual_pct_of_starting_capital"].every(
      (key) =>
        typeof costs[key] === "string" &&
        /^\d+(\.\d+)?$/.test(costs[key] as string),
    ) ||
    ![0, "0", "0.00"].includes(costs.additional_budget_usd as string | number)
  )
    throw new Error("Invalid research or cost data. Controls are unavailable.");
  const hasStockWorker = Object.hasOwn(research, "stock_worker");
  if (hasStockWorker && !validStockWorker(research.stock_worker))
    throw new Error("Invalid stock collector data. Controls are unavailable.");
  if (
    hasStockWorker &&
    (research.stock_worker as StockWorker).status === "unavailable" &&
    (research.opportunities as Row[]).length > 0
  )
    throw new Error(
      "Unavailable stock evidence cannot advertise priorities. Controls are unavailable.",
    );
  for (const row of research.opportunities as Row[]) {
    if (
      (hasStockWorker ||
        row.strategy === "fundamental_screen" ||
        row.status === "unqualified_research" ||
        Object.hasOwn(row, "research_priority_score")) &&
      !isStockOpportunity(row)
    )
      throw new Error("Invalid stock research data. Controls are unavailable.");
  }
  return value as unknown as Snapshot;
}
export class ApiError extends Error {
  constructor(public status: number) {
    super(
      status === 401 || status === 403
        ? "Access denied. Check your dashboard token."
        : `Dashboard request failed (${status}). Try refreshing.`,
    );
  }
}
export async function requestSnapshot(
  token: string,
  action?: Action,
): Promise<Snapshot> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(
      action ? "/api/hybrid/controls" : "/api/hybrid/snapshot",
      {
        method: action ? "POST" : "GET",
        headers: {
          Authorization: `Bearer ${token}`,
          ...(action ? { "Content-Type": "application/json" } : {}),
        },
        ...(action ? { body: JSON.stringify({ action }) } : {}),
        cache: "no-store",
        credentials: "omit",
        redirect: "error",
        signal: controller.signal,
      },
    );
    if (!response.ok) throw new ApiError(response.status);
    return validateSnapshot(await response.json());
  } finally {
    clearTimeout(timeout);
  }
}
export function money(value: unknown): string {
  if (
    typeof value !== "string" ||
    !/^-?\d+(\.\d+)?$/.test(value) ||
    !Number.isFinite(Number(value))
  )
    return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
  }).format(Number(value));
}
export function textValue(value: unknown): string {
  return typeof value === "string" || typeof value === "number"
    ? String(value)
    : typeof value === "boolean"
      ? value
        ? "Yes"
        : "No"
      : "—";
}

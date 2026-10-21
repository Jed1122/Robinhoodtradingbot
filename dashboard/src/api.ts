export type Row = Record<string, unknown>;
export type Action = "pause" | "resume_research" | "kill";
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

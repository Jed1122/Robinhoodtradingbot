import type { Snapshot } from "./api";
// Fictional paper fixture, never seeded into the UI.
export function fixture(): Snapshot {
  return {
    mode: "paper",
    live_enabled: false,
    portfolio: {
      starting_capital: "1000.00",
      equity: "1000.00",
      cash: "1000.00",
      buying_power: "1000.00",
      reserved_cash: "0.00",
      tax_reserve: "0.00",
      realized_gain: "0.00",
      unrealized_gain: "0.00",
      drawdown_pct: "0.00",
      allocations: { long_term: "0.00", tactical: "0.00", reserve: "1000.00" },
      positions: [],
      orders: [],
      lots: [],
    },
    research: {
      regime: "Unknown",
      opportunities: [],
      sources: [],
      strategy_status: [],
      comparisons: [],
      limitations: [],
    },
    safety: {
      paused: true,
      kill_switch: false,
      live_enabled: false,
      paper_period_required: false,
      readiness: [],
      authorization_status: "not_authorized",
    },
    costs: {
      monthly_usd: "12.00",
      annual_pct_of_starting_capital: "14.40",
      additional_budget_usd: 0,
    },
    jobs: [],
    reports: [],
  };
}

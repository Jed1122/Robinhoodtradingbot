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

// Fictional collector evidence for tests; never loaded by the application.
export function stockFixture(): Snapshot {
  const data = fixture();
  data.research.opportunities = [
    {
      symbol: "FICT",
      strategy: "fundamental_screen",
      status: "unqualified_research",
      reason: "Numerical screening priority; further validation is required.",
      research_priority_score: "78.25",
      available_at: "2026-10-21T12:00:00+00:00",
      metrics: {
        roe: "0.18",
        net_margin: "0.12",
        annual_eps_growth: "0.21",
        quarterly_revenue_growth: null,
        earnings_yield: "0.04",
        fcf_yield: null,
      },
      gaps: ["historical_fundamentals_unavailable"],
      dossier_as_of: "2026-10-21T12:10:00Z",
    },
  ];
  data.research.stock_worker = {
    exported_at: new Date().toISOString(),
    last_claim_at: "2026-10-21T12:00:00Z",
    last_result_at: "2026-10-21T12:10:00Z",
    phase: "enrichment",
    status: "succeeded",
    reason: null,
    pending_claims: 0,
    reserved_today: 17,
    daily_limit: 128,
    remaining_calls: 111,
    next_eligible_at: "2026-10-21T12:25:00Z",
    discovery_as_of: "2026-10-21T12:00:00Z",
    enrichment_as_of: "2026-10-21T12:10:00Z",
    control_scope: "separate",
    qualified: false,
    live_enabled: false,
  };
  return data;
}

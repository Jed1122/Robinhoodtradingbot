import type { StockDecisionView } from "./api";
// Fictional response for tests/visual QA only; never seeded into the application.
export function decisionFixture(): StockDecisionView {
  const row = (horizon: "long_term" | "tactical") => ({
    symbol: horizon === "long_term" ? "ALFA" : "BETA", horizon, action: "enter" as const,
    analytically_eligible: true, ordinal_rank: 1, priority_score: "50",
    as_of: "2026-10-26T20:00:00+00:00", source_received_at: "2026-10-26T19:59:00+00:00",
    expires_at: "2026-10-26T21:59:00+00:00", decision_hash: "a".repeat(64),
    bullish_evidence: [{ code: "positive_cash_generation", fact_name: "price_to_fcf", value: "25", basis: "provider_current" }],
    bearish_evidence: [], missing_requirements: [],
    limitations: ["balance_sheet_effective_date_unknown_unless_supplied", "provider_price_signals_not_completed_close"],
    sources: [{tool:"preview_scan",observation_sha256:"b".repeat(64),record_ref:"results/0",received_at:"2026-10-26T19:59:00+00:00"}],
  });
  return { status:"available",schema_version:2,worker_profile_id:"stock-worker-current-provider-v1",
    generated_at:"2026-10-26T20:00:00+00:00",valid_until:"2026-10-26T21:59:00+00:00",source_config_hash:"c".repeat(64),analysis_code_hash:"d".repeat(64),policy_hash:"e".repeat(64),report_body_sha256:"f".repeat(64),report_evidence_hash:"1".repeat(64),plan_status:"research_only",needs:["account_context_missing"],
    long_term:{horizon:"long_term",assessed_count:1,eligible_count:1,omitted_count:0,earliest_eligible_expiry:"2026-10-26T21:59:00+00:00",decisions:[row("long_term")]},
    tactical:{horizon:"tactical",assessed_count:1,eligible_count:1,omitted_count:0,earliest_eligible_expiry:"2026-10-26T21:59:00+00:00",decisions:[row("tactical")]},
    performance_evidence:"unproven_not_a_gate",execution_authorized:false,live_authorized:false,orders_created:false,reservations_created:false };
}

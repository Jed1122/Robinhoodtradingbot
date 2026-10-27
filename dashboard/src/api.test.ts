import { afterEach, describe, expect, it, vi } from "vitest";
import { money, requestSnapshot, validateSnapshot } from "./api";
import { fixture, stockFixture } from "./testFixture";
afterEach(() => vi.unstubAllGlobals());
describe("paper snapshot boundary", () => {
  it("accepts decimal-string paper data and rejects live or malformed safety state", () => {
    expect(validateSnapshot(fixture()).mode).toBe("paper");
    expect(() =>
      validateSnapshot({ ...fixture(), live_enabled: true }),
    ).toThrow();
    expect(() =>
      validateSnapshot({
        ...fixture(),
        safety: { ...fixture().safety, paused: undefined },
      }),
    ).toThrow();
    expect(() =>
      validateSnapshot({
        ...fixture(),
        portfolio: { ...fixture().portfolio, equity: "NaN" },
      }),
    ).toThrow();
    expect(() =>
      validateSnapshot({
        ...fixture(),
        costs: { ...fixture().costs, additional_budget_usd: 20 },
      }),
    ).toThrow();
  });
  it("sends only allowlisted controls through an authorization header with no stored credentials", async () => {
    const storageWrite = vi.fn();
    vi.stubGlobal("localStorage", { setItem: storageWrite });
    vi.stubGlobal("sessionStorage", { setItem: storageWrite });
    const fetcher = vi
      .fn()
      .mockResolvedValue({ ok: true, json: async () => fixture() });
    vi.stubGlobal("fetch", fetcher);
    await requestSnapshot("synthetic-session", "pause");
    expect(fetcher).toHaveBeenCalledWith(
      "/api/hybrid/controls",
      expect.objectContaining({
        method: "POST",
        body: '{"action":"pause"}',
        headers: expect.objectContaining({
          Authorization: "Bearer synthetic-session",
        }),
        credentials: "omit",
        redirect: "error",
        cache: "no-store",
      }),
    );
    expect(storageWrite).not.toHaveBeenCalled();
  });
  it("never surfaces response body or unsafe decimal values", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        json: async () => ({ secret: "private" }),
      }),
    );
    await expect(requestSnapshot("synthetic-session")).rejects.toThrow(
      "Dashboard request failed (500)",
    );
    expect(money("not money")).toBe("—");
    expect(money(undefined)).toBe("—");
    expect(money("12.00")).toBe("$12.00");
  });
});

describe("optional stock collector evidence boundary", () => {
  it("retains compatibility without collector data and accepts the complete stock shape", () => {
    expect(validateSnapshot(fixture()).research.stock_worker).toBeUndefined();
    const data = stockFixture();
    expect(validateSnapshot(data).research.stock_worker?.reserved_today).toBe(
      17,
    );
    expect(
      validateSnapshot(data).research.opportunities[0].research_priority_score,
    ).toBe("78.25");
  });
  it.each(["0", "0.00", "99.999999999999999999", "100.000", "00078.25"])(
    "retains exact valid screening score %s",
    (score) => {
      const data = stockFixture();
      data.research.opportunities[0].research_priority_score = score;
      expect(
        validateSnapshot(data).research.opportunities[0]
          .research_priority_score,
      ).toBe(score);
    },
  );
  it.each([
    ["live_enabled", true],
    ["qualified", true],
    ["control_scope", "hybrid"],
    ["status", "running"],
    ["phase", "execution"],
    ["exported_at", "not a date"],
    ["last_claim_at", "2026-02-30T12:00:00Z"],
    ["last_result_at", "2026-10-21T12:10:00-04:00"],
    ["pending_claims", -1],
    ["reserved_today", 1.5],
    ["reserved_today", 1025],
    ["daily_limit", 0],
    ["remaining_calls", "111"],
    ["remaining_calls", NaN],
    ["remaining_calls", null],
    ["reason", { secret: "private" }],
  ])("rejects malformed or unsafe collector field %s=%s", (key, value) => {
    const data = stockFixture();
    (data.research.stock_worker as unknown as Record<string, unknown>)[key] =
      value;
    expect(() => validateSnapshot(data)).toThrow();
  });
  it("accepts unknown counts only for unavailable exports without inventing zero", () => {
    const data = stockFixture();
    Object.assign(data.research.stock_worker!, {
      status: "unavailable",
      reason: "export_unavailable",
      exported_at: null,
      pending_claims: null,
      reserved_today: null,
      daily_limit: null,
      remaining_calls: null,
    });
    data.research.opportunities = [];
    expect(
      validateSnapshot(data).research.stock_worker?.remaining_calls,
    ).toBeNull();
    data.research.stock_worker!.status = "never_run";
    expect(() => validateSnapshot(data)).toThrow();
  });
  it.each([
    ["research_priority_score", "NaN"],
    ["research_priority_score", "100.01"],
    ["research_priority_score", "100.000000000000000001"],
    ["research_priority_score", "-1"],
    ["research_priority_score", 78.25],
    ["symbol", ""],
    ["status", "approved"],
    ["strategy", "buy_now"],
    ["available_at", "2026-02-30T12:00:00Z"],
    ["dossier_as_of", "tomorrow"],
    ["metrics", { roe: "0.18" }],
    ["gaps", ["missing", 3]],
  ])("rejects invalid stock opportunity field %s=%s", (key, value) => {
    const data = stockFixture();
    data.research.opportunities[0][key] = value;
    expect(() => validateSnapshot(data)).toThrow();
  });
  it.each(["NaN", "Infinity", 0.18, false, undefined])(
    "rejects non-decimal stock metric %s",
    (value) => {
      const data = stockFixture();
      (data.research.opportunities[0].metrics as Record<string, unknown>).roe =
        value;
      expect(() => validateSnapshot(data)).toThrow();
    },
  );
  it("validates stock-marked rows even without collector metadata", () => {
    const data = stockFixture();
    delete data.research.stock_worker;
    data.research.opportunities[0].research_priority_score = "101";
    expect(() => validateSnapshot(data)).toThrow();
  });
  it("rejects unavailable exports that still advertise stock priorities", () => {
    const data = stockFixture();
    data.research.stock_worker!.status = "unavailable";
    expect(() => validateSnapshot(data)).toThrow();
  });
});
it("accepts explicit unknown valuations but rejects unknown cash-state fields", () => {
  const unknown = fixture();
  unknown.portfolio.equity = null;
  unknown.portfolio.unrealized_gain = null;
  unknown.portfolio.drawdown_pct = null;
  unknown.portfolio.valuation_status = "marks_unavailable";
  unknown.portfolio.allocations.long_term = null;
  unknown.portfolio.allocations.tactical = null;
  const verified = validateSnapshot(unknown);
  expect(verified.portfolio.equity).toBeNull();
  expect(verified.portfolio.allocations.long_term).toBeNull();
  expect(money(verified.portfolio.equity)).toBe("—");
  for (const key of [
    "cash",
    "starting_capital",
    "buying_power",
    "reserved_cash",
    "tax_reserve",
    "realized_gain",
  ]) {
    expect(() =>
      validateSnapshot({
        ...unknown,
        portfolio: { ...unknown.portfolio, [key]: null },
      }),
    ).toThrow();
  }
  expect(() =>
    validateSnapshot({
      ...unknown,
      portfolio: {
        ...unknown.portfolio,
        allocations: { ...unknown.portfolio.allocations, reserve: null },
      },
    }),
  ).toThrow();
  expect(() =>
    validateSnapshot({
      ...unknown,
      portfolio: { ...unknown.portfolio, equity: undefined },
    }),
  ).toThrow();
});

import { decisionFixture } from "./decisionTestFixture";
it("accepts optional current decisions while rejecting authority, clocks and incomplete denominators", () => {
  const snapshot = fixture();
  snapshot.research.current_decisions = decisionFixture();
  expect(validateSnapshot(snapshot)).toBe(snapshot);
  const bad = structuredClone(snapshot);
  (bad.research.current_decisions as unknown as Record<string, unknown>).live_authorized = true;
  expect(() => validateSnapshot(bad)).toThrow();
  const counts = structuredClone(snapshot);
  if (counts.research.current_decisions?.status === "available") counts.research.current_decisions.long_term.assessed_count = 2;
  expect(() => validateSnapshot(counts)).toThrow();
});

it("rejects an eligible count unsupported by a complete displayed inventory", () => {
  const data = fixture();
  const view = decisionFixture();
  if (view.status !== "available") throw new Error("fixture must be available");
  Object.assign(view.long_term.decisions[0], {
    analytically_eligible: false, action: "review", ordinal_rank: null,
    priority_score: null, expires_at: null,
  });
  data.research.current_decisions = view;
  expect(() => validateSnapshot(data)).toThrow();
});

it("allows a truthful eligible lower bound when additional decisions are omitted", () => {
  const data = fixture();
  const view = decisionFixture();
  if (view.status !== "available") throw new Error("fixture must be available");
  view.long_term.assessed_count = 2;
  view.long_term.eligible_count = 2;
  view.long_term.omitted_count = 1;
  data.research.current_decisions = view;
  expect(validateSnapshot(data)).toBe(data);
});

it.each(["legacy_version", "missing_aggregate", "null_aggregate", "late_aggregate", "bad_aggregate", "missing_deadline", "late_deadline"])("rejects invalid current-decision expiry coverage: %s", (kind) => {
  const data = fixture();
  const view = decisionFixture();
  if (view.status !== "available") throw new Error("fixture must be available");
  const raw = view as unknown as Record<string, unknown>;
  if (kind === "legacy_version") raw.schema_version = 1;
  if (kind === "missing_aggregate") delete (view.long_term as unknown as Record<string, unknown>).earliest_eligible_expiry;
  if (kind === "null_aggregate") view.long_term.earliest_eligible_expiry = null;
  if (kind === "late_aggregate") view.long_term.earliest_eligible_expiry = "2026-10-26T22:00:00Z";
  if (kind === "bad_aggregate") (view.long_term as unknown as Record<string, unknown>).earliest_eligible_expiry = true;
  if (kind === "missing_deadline") delete raw.valid_until;
  if (kind === "late_deadline") view.valid_until = "2026-10-26T22:00:00Z";
  data.research.current_decisions = view;
  expect(() => validateSnapshot(data)).toThrow();
});

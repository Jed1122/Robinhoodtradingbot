import { afterEach, describe, expect, it, vi } from "vitest";
import { money, requestSnapshot, validateSnapshot } from "./api";
import { fixture } from "./testFixture";
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

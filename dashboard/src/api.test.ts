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
      vi
        .fn()
        .mockResolvedValue({
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

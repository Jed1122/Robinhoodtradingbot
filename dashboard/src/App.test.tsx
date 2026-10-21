import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App";
import { fixture, stockFixture } from "./testFixture";
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("renders stock research priorities with original times and separate collector controls", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValue({ ok: true, json: async () => stockFixture() });
  vi.stubGlobal("fetch", fetcher);
  const user = userEvent.setup();
  render(<App />);
  await user.type(
    screen.getByLabelText("Dashboard access token"),
    "synthetic-session",
  );
  await user.click(screen.getByRole("button", { name: "Connect workspace" }));
  await screen.findByText("Connected");
  await user.click(screen.getByRole("button", { name: "Research" }));
  expect(
    screen.getByRole("heading", { name: "Stock research priorities" }),
  ).toBeTruthy();
  expect(screen.getByText("FICT")).toBeTruthy();
  expect(screen.getByText("78.25 / 100")).toBeTruthy();
  expect(screen.getAllByText("2026-10-21 12:00:00 UTC").length).toBeGreaterThan(
    0,
  );
  expect(
    screen.getByText(/Research priority is a screening rank/),
  ).toBeTruthy();
  expect(screen.getByText("17 / 128 calls reserved today")).toBeTruthy();
  expect(screen.getByText("111 calls remaining")).toBeTruthy();
  expect(screen.getByText("Succeeded (last cycle)")).toBeTruthy();
  await user.click(screen.getByText("Company evidence"));
  expect(screen.getByText("historical_fundamentals_unavailable")).toBeTruthy();
  expect(screen.getByText("0.18")).toBeTruthy();
  await user.click(screen.getByRole("button", { name: "Settings" }));
  expect(
    screen.getByText(/The stock collector uses a separate control scope/),
  ).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Resume research" })).toBeNull();
  await user.click(
    screen.getByRole("button", { name: "Resume hybrid research" }),
  );
  await screen.findByText(
    "Hybrid research resumed. The separate stock collector is unaffected. Live trading remains disabled.",
  );
  expect(fetcher).toHaveBeenLastCalledWith(
    "/api/hybrid/controls",
    expect.objectContaining({ body: '{"action":"resume_research"}' }),
  );
});

it.each([
  [
    "pause",
    "Pause hybrid research",
    "Hybrid research paused. The separate stock collector is unaffected.",
  ],
  [
    "resume_research",
    "Resume hybrid research",
    "Hybrid research resumed. The separate stock collector is unaffected. Live trading remains disabled.",
  ],
  [
    "kill",
    "Activate hybrid kill switch",
    "Hybrid kill switch activated. The separate stock collector is unaffected.",
  ],
])(
  "keeps %s scoped to hybrid research when stock priorities omit collector metadata",
  async (action, label, notice) => {
    const data = stockFixture();
    delete data.research.stock_worker;
    data.safety.paused = action === "resume_research";
    const fetcher = vi
      .fn()
      .mockResolvedValue({ ok: true, json: async () => data });
    vi.stubGlobal("fetch", fetcher);
    const user = userEvent.setup();
    render(<App />);
    await user.type(
      screen.getByLabelText("Dashboard access token"),
      "synthetic-session",
    );
    await user.click(screen.getByRole("button", { name: "Connect workspace" }));
    await screen.findByText("Connected");
    await user.click(screen.getByRole("button", { name: "Research" }));
    expect(
      screen.getByRole("heading", { name: "Stock research priorities" }),
    ).toBeTruthy();
    expect(
      screen.queryByRole("heading", { name: "Stock collector" }),
    ).toBeNull();
    await user.click(screen.getByRole("button", { name: "Settings" }));
    expect(
      screen.getByRole("heading", { name: "Hybrid portfolio controls" }),
    ).toBeTruthy();
    expect(
      screen.getByText(/The stock collector uses a separate control scope/),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Pause hybrid research" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Resume hybrid research" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Activate hybrid kill switch" }),
    ).toBeTruthy();
    await user.click(screen.getByRole("button", { name: label }));
    await screen.findByText(notice);
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(fetcher).toHaveBeenLastCalledWith(
      "/api/hybrid/controls",
      expect.objectContaining({ body: JSON.stringify({ action }) }),
    );
  },
);

it("shows unavailable collector budgets as unknown and does not imply continuous operation", async () => {
  const data = stockFixture();
  data.research.opportunities = [];
  Object.assign(data.research.stock_worker!, {
    status: "unavailable",
    reason: "stale_export",
    exported_at: null,
    pending_claims: null,
    reserved_today: null,
    daily_limit: null,
    remaining_calls: null,
  });
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: true, json: async () => data }),
  );
  const user = userEvent.setup();
  render(<App />);
  await user.type(
    screen.getByLabelText("Dashboard access token"),
    "synthetic-session",
  );
  await user.click(screen.getByRole("button", { name: "Connect workspace" }));
  await screen.findByText("Connected");
  await user.click(screen.getByRole("button", { name: "Research" }));
  expect(screen.getByText("Collector evidence unavailable")).toBeTruthy();
  expect(screen.getByText("stale_export")).toBeTruthy();
  expect(screen.getByText("Call budget unknown")).toBeTruthy();
  expect(screen.getByText("Remaining calls unknown")).toBeTruthy();
  expect(screen.getByText("No current stock research priorities")).toBeTruthy();
  expect(screen.queryByText("0 calls remaining")).toBeNull();
});
it("connects, navigates, submits research controls, then clears the session", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValue({ ok: true, json: async () => fixture() });
  vi.stubGlobal("fetch", fetcher);
  const user = userEvent.setup();
  render(<App />);
  expect(screen.getByText("Disconnected")).toBeTruthy();
  await user.type(
    screen.getByLabelText("Dashboard access token"),
    "synthetic-session",
  );
  await user.click(screen.getByRole("button", { name: "Connect workspace" }));
  await screen.findByText("Connected");
  expect(screen.queryByLabelText("Dashboard access token")).toBeNull();
  await user.click(screen.getByRole("button", { name: "Research" }));
  expect(screen.getByText("No sources recorded")).toBeTruthy();
  await user.click(screen.getByRole("button", { name: "Trades" }));
  expect(screen.getByText("No paper orders recorded")).toBeTruthy();
  await user.click(screen.getByRole("button", { name: "Settings" }));
  await user.click(screen.getByRole("button", { name: "Resume research" }));
  await waitFor(() =>
    expect(fetcher).toHaveBeenLastCalledWith(
      "/api/hybrid/controls",
      expect.objectContaining({ body: '{"action":"resume_research"}' }),
    ),
  );
  await screen.findByText("Research resumed. Live trading remains disabled.");
  await user.click(
    screen.getByRole("button", { name: "Disconnect & clear token" }),
  );
  expect(screen.getByText("Disconnected")).toBeTruthy();
  expect(
    screen.getByLabelText("Dashboard access token").getAttribute("value"),
  ).toBe("");
});
it("labels a stale dashboard response as recorded collector evidence and blocks its controls", async () => {
  const data = { ...stockFixture(), generated_at: "2000-01-01T00:00:00Z" };
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: true, json: async () => data }),
  );
  const user = userEvent.setup();
  render(<App />);
  await user.type(
    screen.getByLabelText("Dashboard access token"),
    "synthetic-session",
  );
  await user.click(screen.getByRole("button", { name: "Connect workspace" }));
  await screen.findByText("Snapshot stale");
  await user.click(screen.getByRole("button", { name: "Research" }));
  expect(
    screen.getByText(
      "Dashboard snapshot is stale. Collector activity is not current.",
    ),
  ).toBeTruthy();
  await user.click(screen.getByRole("button", { name: "Settings" }));
  expect(
    (
      screen.getByRole("button", {
        name: "Resume hybrid research",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(
    (
      screen.getByRole("button", {
        name: "Activate hybrid kill switch",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
});

it("disables controls when snapshots become invalid or stale", async () => {
  const data = { ...fixture(), generated_at: "2000-01-01T00:00:00Z" };
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: true, json: async () => data }),
  );
  const user = userEvent.setup();
  render(<App />);
  await user.type(
    screen.getByLabelText("Dashboard access token"),
    "synthetic-session",
  );
  await user.click(screen.getByRole("button", { name: "Connect workspace" }));
  await screen.findByText("Snapshot stale");
  await user.click(screen.getByRole("button", { name: "Settings" }));
  expect(
    (
      screen.getByRole("button", {
        name: "Resume research",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(
    (
      screen.getByRole("button", {
        name: "Activate kill switch",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
});
it("rejects live snapshots without presenting them as connected", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ...fixture(), live_enabled: true }),
    }),
  );
  const user = userEvent.setup();
  render(<App />);
  await user.type(
    screen.getByLabelText("Dashboard access token"),
    "synthetic-session",
  );
  await user.click(screen.getByRole("button", { name: "Connect workspace" }));
  await screen.findByRole("alert");
  expect(screen.getByText("Disconnected")).toBeTruthy();
});
it("clears connected evidence and the token after authorization is revoked", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce({ ok: true, json: async () => fixture() })
    .mockResolvedValueOnce({ ok: false, status: 401 });
  vi.stubGlobal("fetch", fetcher);
  const user = userEvent.setup();
  render(<App />);
  await user.type(
    screen.getByLabelText("Dashboard access token"),
    "synthetic-session",
  );
  await user.click(screen.getByRole("button", { name: "Connect workspace" }));
  await screen.findByText("Connected");
  await user.click(screen.getByRole("button", { name: "Refresh" }));
  await screen.findByText("Access denied. Check your dashboard token.");
  expect(screen.getByText("Disconnected")).toBeTruthy();
  expect(
    screen.getByLabelText("Dashboard access token").getAttribute("value"),
  ).toBe("");
  expect(screen.queryByText("$1,000.00")).toBeNull();
});
it("shows unavailable marks as unknown valuations without fabricating zero returns", async () => {
  const data = fixture();
  data.portfolio.equity = null;
  data.portfolio.unrealized_gain = null;
  data.portfolio.drawdown_pct = null;
  data.portfolio.valuation_status = "marks_unavailable";
  data.portfolio.allocations.long_term = null;
  data.portfolio.allocations.tactical = null;
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: true, json: async () => data }),
  );
  const user = userEvent.setup();
  render(<App />);
  await user.type(
    screen.getByLabelText("Dashboard access token"),
    "synthetic-session",
  );
  await user.click(screen.getByRole("button", { name: "Connect workspace" }));
  await screen.findByText("Connected");
  expect(screen.getByText(/valuation_status: marks_unavailable/)).toBeTruthy();
  const equity = screen.getByText("Portfolio equity", {
    selector: "div.metric-label",
  }).parentElement!;
  const gains = screen.getByText("Unrealized gain / loss").parentElement!;
  expect(equity.querySelector("strong")?.textContent).toBe("—");
  expect(gains.querySelector("strong")?.textContent).toBe("—");
  expect(
    screen.getByText("Available cash").parentElement?.querySelector("strong")
      ?.textContent,
  ).toBe("$1,000.00");
  await user.click(screen.getByRole("button", { name: "Analytics" }));
  const drawdown = screen.getByText("Drawdown").parentElement!;
  expect(drawdown.querySelector("strong")?.textContent).toBe("—");
  expect(screen.queryByText("null%")).toBeNull();
});

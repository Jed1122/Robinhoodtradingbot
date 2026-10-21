import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App";
import { fixture } from "./testFixture";
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
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
    vi
      .fn()
      .mockResolvedValue({
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

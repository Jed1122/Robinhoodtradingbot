import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  Activity,
  ArrowDownLeft,
  ArrowUpRight,
  BarChart3,
  BookOpen,
  Check,
  ChevronRight,
  CirclePause,
  LayoutDashboard,
  LockKeyhole,
  LogOut,
  RefreshCw,
  Settings,
  ShieldCheck,
  Square,
  Wallet,
} from "lucide-react";
import {
  ApiError,
  money,
  requestSnapshot,
  textValue,
  type Action,
  type Row,
  type Snapshot,
} from "./api";
const pages = [
  "Overview",
  "Research",
  "Trades",
  "Analytics",
  "Settings",
] as const;
type Page = (typeof pages)[number];
const icons = [LayoutDashboard, BookOpen, ArrowDownLeft, BarChart3, Settings];
function Empty({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="empty">
      <span className="empty-icon">
        <Activity size={21} />
      </span>
      <strong>{title}</strong>
      <p>{children}</p>
    </div>
  );
}
function Panel({
  title,
  note,
  children,
}: {
  title: string;
  note?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="panel">
      <div className="panel-title">
        <h2>{title}</h2>
        {note && <span>{note}</span>}
      </div>
      {children}
    </section>
  );
}
function DataTable({
  rows,
  columns,
  empty,
  detail = false,
}: {
  rows: Row[];
  columns: [string, string][];
  empty: string;
  detail?: boolean;
}) {
  return rows.length ? (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            {columns.map(([key, label]) => (
              <th key={key}>{label}</th>
            ))}
            {detail && <th>Evidence</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {columns.map(([key]) => (
                <td key={key}>{textValue(row[key])}</td>
              ))}
              {detail && (
                <td>
                  <details>
                    <summary>View details</summary>
                    <pre>{JSON.stringify(row, null, 2)}</pre>
                  </details>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  ) : (
    <Empty title={empty}>
      Records will appear here when the research service supplies evidence.
    </Empty>
  );
}
function Metric({
  label,
  value,
  note,
  icon: Icon,
}: {
  label: string;
  value: string;
  note: string;
  icon: typeof Wallet;
}) {
  return (
    <div className="metric">
      <div className="metric-label">
        {label}
        <Icon size={17} />
      </div>
      <strong>{value}</strong>
      <span>{note}</span>
    </div>
  );
}
export default function App() {
  const [page, setPage] = useState<Page>("Overview");
  const [token, setToken] = useState("");
  const [draft, setDraft] = useState("");
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [fetched, setFetched] = useState<number | null>(null);
  const [now, setNow] = useState(Date.now());
  const [notice, setNotice] = useState("");
  const generation = useRef(0);
  const busy = useRef(false);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 10000);
    return () => clearInterval(timer);
  }, []);
  const sourceTime = snapshot?.generated_at
    ? Date.parse(snapshot.generated_at)
    : NaN;
  const stale =
    fetched !== null &&
    (now - fetched > 60000 ||
      (Number.isFinite(sourceTime) && now - sourceTime > 60000));
  async function load(activeToken = token, action?: Action) {
    if (busy.current) return;
    busy.current = true;
    const request = ++generation.current;
    setPending(true);
    setError("");
    setNotice("");
    try {
      const data = await requestSnapshot(activeToken, action);
      if (generation.current !== request) return;
      setSnapshot(data);
      setToken(activeToken);
      setDraft("");
      setFetched(Date.now());
      setNow(Date.now());
      if (action)
        setNotice(
          action === "kill"
            ? "Kill switch activated."
            : action === "pause"
              ? "Research paused."
              : "Research resumed. Live trading remains disabled.",
        );
    } catch (err) {
      if (generation.current !== request) return;
      setError(
        err instanceof ApiError
          ? err.message
          : "Unable to load a verified snapshot. Check the service connection and refresh.",
      );
      if (err instanceof ApiError && [401, 403].includes(err.status)) {
        setToken("");
        setSnapshot(null);
        setFetched(null);
      }
    } finally {
      if (generation.current === request) {
        busy.current = false;
        setPending(false);
      }
    }
  }
  function disconnect() {
    generation.current++;
    busy.current = false;
    setToken("");
    setDraft("");
    setSnapshot(null);
    setFetched(null);
    setError("");
    setNotice("");
    setPending(false);
  }
  function connect(event: FormEvent) {
    event.preventDefault();
    if (draft.trim()) void load(draft.trim());
  }
  const safeControls = !!snapshot && !pending && !error && !stale;
  const p = snapshot?.portfolio;
  const research = snapshot?.research;
  const safety = snapshot?.safety;
  return (
    <div className="workspace">
      <a className="skip" href="#main">
        Skip to content
      </a>
      <aside className="sidebar">
        <a
          className="brand"
          href="#overview"
          onClick={() => setPage("Overview")}
        >
          <span className="brand-mark">
            <Activity size={22} />
          </span>
          hybrid<span className="brand-dot">.</span>
        </a>
        <div className="workspace-name">RESEARCH WORKSPACE</div>
        <nav aria-label="Main navigation">
          {pages.map((item, i) => {
            const Icon = icons[i];
            return (
              <button
                key={item}
                aria-current={page === item ? "page" : undefined}
                className={page === item ? "nav-item active" : "nav-item"}
                onClick={() => setPage(item)}
              >
                <Icon size={18} />
                {item}
                {page === item && (
                  <ChevronRight className="nav-arrow" size={15} />
                )}
              </button>
            );
          })}
        </nav>
        <div className="sidebar-bottom">
          <div className="paper-label">
            <span className="status-dot" />
            Paper environment
          </div>
          <p>
            Research with guardrails.
            <br />
            Live trading is disabled.
          </p>
          <div className="sidebar-rule" />
          <div className="operator">
            <span className="operator-icon">
              <LockKeyhole size={17} />
            </span>
            <div>
              Private workspace<small>Local dashboard session</small>
            </div>
          </div>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <span>
            Workspace <ChevronRight size={14} /> <strong>{page}</strong>
          </span>
          <div className="topbar-right">
            <span className="live-lock">
              <LockKeyhole size={13} /> Live disabled
            </span>
            <span className="connection">
              <span
                className={`status-dot ${error || !snapshot ? "gray" : stale ? "amber" : ""}`}
              />
              {!snapshot
                ? "Disconnected"
                : error
                  ? "Connection lost"
                  : stale
                    ? "Snapshot stale"
                    : "Connected"}
            </span>
          </div>
        </header>
        <main id="main">
          <div className="page-heading">
            <div>
              <h1>{page === "Overview" ? "Portfolio overview" : page}</h1>
              <p>
                {
                  {
                    Overview:
                      "A clear view of your capital, research, and safeguards.",
                    Research: "Evaluate opportunities against the evidence.",
                    Trades: "Inspect paper positions, orders, and tax lots.",
                    Analytics: "Review recorded comparisons and reports.",
                    Settings: "Inspect safeguards and manage this session.",
                  }[page]
                }
              </p>
            </div>
            <div className="heading-actions">
              {token && (
                <button
                  className="button secondary"
                  onClick={() => void load()}
                  disabled={pending}
                >
                  <RefreshCw size={15} className={pending ? "spin" : ""} />
                  {pending ? "Refreshing…" : "Refresh"}
                </button>
              )}
            </div>
          </div>
          {error && (
            <div role="alert" className="alert">
              {error}
              {snapshot &&
                " Last verified values remain visible; controls are disabled."}
            </div>
          )}
          {notice && (
            <div role="status" className="notice">
              <Check size={16} />
              {notice}
            </div>
          )}
          {!token && (
            <section className="connect-panel">
              <div className="connect-icon">
                <LockKeyhole size={23} />
              </div>
              <div>
                <h2>Connect to your research service</h2>
                <p>
                  Enter your dashboard access token. It stays in memory for this
                  session and is cleared when you disconnect or reload.
                </p>
                <form onSubmit={connect}>
                  <label htmlFor="token">Dashboard access token</label>
                  <div className="connect-row">
                    <input
                      id="token"
                      type="password"
                      value={draft}
                      onChange={(e) => setDraft(e.target.value)}
                      autoComplete="off"
                      spellCheck={false}
                      required
                      placeholder="Enter access token"
                    />
                    <button
                      className="button primary"
                      disabled={pending || !draft.trim()}
                    >
                      {pending ? "Connecting…" : "Connect workspace"}
                      <ArrowUpRight size={16} />
                    </button>
                  </div>
                </form>
              </div>
            </section>
          )}
          <div className="safety-banner">
            <ShieldCheck size={20} />
            <div>
              <strong>Paper research only</strong>
              <span>
                Live authorization: not authorized. This workspace cannot enable
                live trading or submit broker orders.
              </span>
            </div>
            <span className="safety-tag">Protected</span>
          </div>
          {p &&
            (p.valuation_status === "marks_unavailable" ||
              p.equity === null ||
              p.unrealized_gain === null ||
              p.drawdown_pct === null ||
              p.allocations.long_term === null ||
              p.allocations.tactical === null) && (
              <div role="status" className="alert">
                Current marks unavailable (valuation_status: marks_unavailable).
                Unknown equity, gains, drawdown, or allocations are shown as —.
                Cash values remain as reported.
              </div>
            )}
          {page === "Overview" && (
            <>
              <div className="metrics">
                <Metric
                  label="Portfolio equity"
                  value={money(p?.equity)}
                  note={
                    p
                      ? `Starting capital ${money(p.starting_capital)}`
                      : "Awaiting a verified snapshot"
                  }
                  icon={Wallet}
                />
                <Metric
                  label="Available cash"
                  value={money(p?.cash)}
                  note={
                    p
                      ? `${money(p.reserved_cash)} reserved`
                      : "No account data loaded"
                  }
                  icon={ArrowDownLeft}
                />
                <Metric
                  label="Unrealized gain / loss"
                  value={money(p?.unrealized_gain)}
                  note={
                    p?.unrealized_gain === null
                      ? "Current marks unavailable"
                      : "Paper portfolio only"
                  }
                  icon={BarChart3}
                />
                <Metric
                  label="Monthly operating cost"
                  value={money(snapshot?.costs.monthly_usd)}
                  note={
                    snapshot
                      ? `${snapshot.costs.annual_pct_of_starting_capital}% of starting capital annually`
                      : "No cost data loaded"
                  }
                  icon={Activity}
                />
              </div>
              <div className="overview-grid">
                <Panel title="Capital allocation" note="Current snapshot">
                  {p ? (
                    <>
                      <div className="allocation-total">
                        <span>Portfolio equity</span>
                        <strong>{money(p.equity)}</strong>
                      </div>
                      <div className="allocation-list">
                        {(["long_term", "tactical", "reserve"] as const).map(
                          (key, i) => (
                            <div key={key}>
                              <span>
                                <i className={`allocation-dot color-${i}`} />
                                {
                                  {
                                    long_term: "Long-term",
                                    tactical: "Tactical",
                                    reserve: "Reserve",
                                  }[key]
                                }
                              </span>
                              <strong>{money(p.allocations[key])}</strong>
                            </div>
                          ),
                        )}
                      </div>
                      <p className="panel-footnote">
                        Reported allocations; no performance history is
                        inferred.
                      </p>
                    </>
                  ) : (
                    <Empty title="Capital data unavailable">
                      Connect your service to view the current allocation.
                    </Empty>
                  )}
                </Panel>
                <Panel
                  title="Research activity"
                  note={
                    research
                      ? "Evidence from the service"
                      : "Awaiting connection"
                  }
                >
                  <DataTable
                    rows={snapshot?.jobs ?? []}
                    columns={[
                      ["name", "Research job"],
                      ["status", "Status"],
                      ["updated_at", "Updated"],
                    ]}
                    empty="No research jobs recorded"
                  />
                </Panel>
              </div>
              <Panel
                title="Research opportunities"
                note={`${research?.opportunities.length ?? 0} recorded`}
              >
                <DataTable
                  rows={research?.opportunities ?? []}
                  columns={[
                    ["symbol", "Symbol"],
                    ["strategy", "Strategy"],
                    ["status", "Status"],
                    ["reason", "Rationale"],
                  ]}
                  empty="No qualified opportunities yet"
                  detail
                />
              </Panel>
            </>
          )}
          {page === "Research" && (
            <>
              <div className="regime">
                <span>Market regime</span>
                <strong>
                  {typeof research?.regime === "string"
                    ? research.regime
                    : research?.regime
                      ? textValue(
                          research.regime.name ?? research.regime.status,
                        )
                      : "Unknown"}
                </strong>
                <p>
                  Regime labels describe research inputs; they do not authorize
                  trading.
                </p>
              </div>
              <Panel title="Strategy research">
                <DataTable
                  rows={research?.strategy_status ?? []}
                  columns={[
                    ["name", "Strategy"],
                    ["status", "Status"],
                    ["reason", "Reason"],
                  ]}
                  empty="No strategy evidence available"
                  detail
                />
              </Panel>
              <Panel title="Source evidence">
                <DataTable
                  rows={research?.sources ?? []}
                  columns={[
                    ["name", "Source"],
                    ["status", "Status"],
                    ["as_of", "As of"],
                  ]}
                  empty="No sources recorded"
                  detail
                />
              </Panel>
              <Panel title="Known limitations">
                {research?.limitations.length ? (
                  <ul className="limitations">
                    {research.limitations.map((item, i) => (
                      <li key={i}>{item}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="plain-note">
                    No limitations supplied. This does not establish data
                    completeness or readiness.
                  </p>
                )}
              </Panel>
            </>
          )}
          {page === "Trades" && (
            <>
              <Panel title="Paper positions">
                <DataTable
                  rows={p?.positions ?? []}
                  columns={[
                    ["symbol", "Symbol"],
                    ["quantity", "Quantity"],
                    ["market_value", "Market value (USD)"],
                    ["unrealized_gain", "Unrealized gain (USD)"],
                  ]}
                  empty="No paper positions recorded"
                />
              </Panel>
              <Panel title="Paper orders">
                <DataTable
                  rows={p?.orders ?? []}
                  columns={[
                    ["symbol", "Symbol"],
                    ["side", "Side"],
                    ["quantity", "Quantity"],
                    ["status", "Status"],
                  ]}
                  empty="No paper orders recorded"
                />
              </Panel>
              <Panel title="Tax lots">
                <DataTable
                  rows={p?.lots ?? []}
                  columns={[
                    ["symbol", "Symbol"],
                    ["quantity", "Quantity"],
                    ["cost_basis", "Cost basis (USD)"],
                    ["acquired_at", "Acquired"],
                  ]}
                  empty="No tax lots recorded"
                />
              </Panel>
            </>
          )}
          {page === "Analytics" && (
            <>
              <div className="metrics">
                <Metric
                  label="Realized gain / loss"
                  value={money(p?.realized_gain)}
                  note="Recorded paper activity"
                  icon={BarChart3}
                />
                <Metric
                  label="Tax reserve"
                  value={money(p?.tax_reserve)}
                  note="Reported reserve only"
                  icon={Wallet}
                />
                <Metric
                  label="Buying power"
                  value={money(p?.buying_power)}
                  note="Reported paper buying power"
                  icon={Activity}
                />
                <Metric
                  label="Drawdown"
                  value={p?.drawdown_pct != null ? `${p.drawdown_pct}%` : "—"}
                  note={
                    p?.drawdown_pct === null
                      ? "Current marks unavailable"
                      : "From the current snapshot"
                  }
                  icon={ArrowDownLeft}
                />
              </div>
              <Panel title="Recorded comparisons">
                <DataTable
                  rows={research?.comparisons ?? []}
                  columns={[
                    ["name", "Comparison"],
                    ["status", "Status"],
                  ]}
                  empty="No comparison evidence yet"
                  detail
                />
              </Panel>
              <Panel title="Research reports">
                <DataTable
                  rows={snapshot?.reports ?? []}
                  columns={[
                    ["name", "Report"],
                    ["status", "Status"],
                    ["created_at", "Created"],
                  ]}
                  empty="No research reports recorded"
                  detail
                />
              </Panel>
            </>
          )}
          {page === "Settings" && (
            <>
              <Panel title="Safety controls">
                <div className="control-content">
                  <dl className="safety-values">
                    <div>
                      <dt>Research state</dt>
                      <dd>
                        {safety
                          ? safety.paused
                            ? "Paused"
                            : "Running"
                          : "Unknown"}
                      </dd>
                    </div>
                    <div>
                      <dt>Kill switch</dt>
                      <dd>
                        {safety
                          ? safety.kill_switch
                            ? "Activated"
                            : "Not activated"
                          : "Unknown"}
                      </dd>
                    </div>
                    <div>
                      <dt>Live authorization</dt>
                      <dd>Not authorized</dd>
                    </div>
                    <div>
                      <dt>Paper period requirement</dt>
                      <dd>
                        {safety
                          ? safety.paper_period_required
                            ? "Required"
                            : "Not required by service"
                          : "Unknown"}
                      </dd>
                    </div>
                  </dl>
                  <p>
                    Resume affects research only. A kill switch cannot be
                    cleared from this dashboard.
                  </p>
                  <div className="controls">
                    <button
                      className="button secondary"
                      disabled={!safeControls || safety?.paused}
                      onClick={() => void load(token, "pause")}
                    >
                      <CirclePause size={16} />
                      Pause research
                    </button>
                    <button
                      className="button secondary"
                      disabled={
                        !safeControls || !safety?.paused || safety?.kill_switch
                      }
                      onClick={() => void load(token, "resume_research")}
                    >
                      <Activity size={16} />
                      Resume research
                    </button>
                    <button
                      className="button danger"
                      disabled={!safeControls || safety?.kill_switch}
                      onClick={() => void load(token, "kill")}
                    >
                      <Square size={14} />
                      Activate kill switch
                    </button>
                  </div>
                </div>
              </Panel>
              <Panel title="Readiness evidence">
                <DataTable
                  rows={safety?.readiness ?? []}
                  columns={[
                    ["name", "Gate"],
                    ["status", "Status"],
                    ["reason", "Reason"],
                  ]}
                  empty="No readiness evidence supplied"
                  detail
                />
              </Panel>
              <Panel title="Session & operating budget">
                <div className="control-content">
                  <p>
                    Additional spending authorized:{" "}
                    {snapshot
                      ? money(String(snapshot.costs.additional_budget_usd))
                      : "unknown"}
                    . Access tokens are never saved in browser storage.
                  </p>
                  <button
                    className="button secondary"
                    disabled={!token}
                    onClick={disconnect}
                  >
                    <LogOut size={16} />
                    Disconnect & clear token
                  </button>
                </div>
              </Panel>
            </>
          )}
          <footer>
            <span>
              <ShieldCheck size={14} />
              Research and paper results are not expected live performance.
            </span>
            <span>
              {fetched
                ? `Retrieved ${new Date(fetched).toLocaleTimeString()}${stale ? " · Stale — refresh before controls" : ""}`
                : "No verified snapshot"}
              {Number.isFinite(sourceTime) &&
                ` · Source ${new Date(sourceTime).toLocaleString()}`}
            </span>
          </footer>
        </main>
      </div>
    </div>
  );
}

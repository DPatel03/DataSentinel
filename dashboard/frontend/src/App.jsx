import { useEffect, useState } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import { fetchApi, setAuthToken } from "./api";

function StatCard({ title, value, sub, tone }) {
  return (
    <div className={`card ${tone ? `tone-${tone}` : ""}`}>
      <h3>{title}</h3>
      <div className="value">{value}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  );
}

function repairDiff(original, repaired) {
  if (!original || !repaired) return [];
  return Object.keys({ ...original, ...repaired })
    .filter((k) => JSON.stringify(original[k]) !== JSON.stringify(repaired[k]))
    .map((k) => ({ field: k, from: original[k], to: repaired[k] }));
}

export default function App() {
  const [overview, setOverview] = useState(null);
  const [failures, setFailures] = useState([]);
  const [repairs, setRepairs] = useState([]);
  const [prompts, setPrompts] = useState([]);
  const [reviewQueue, setReviewQueue] = useState([]);
  const [breaches, setBreaches] = useState([]);
  const [traces, setTraces] = useState([]);
  const [evalResults, setEvalResults] = useState(null);
  const [error, setError] = useState(null);
  const [needsAuth, setNeedsAuth] = useState(false);
  const [tokenInput, setTokenInput] = useState("");
  const [detail, setDetail] = useState(null);

  async function load() {
    try {
      const [ov, fr, rp, pr, rq, br, lt, ev] = await Promise.all([
        fetchApi("/stats/overview"),
        fetchApi("/stats/failure-rate"),
        fetchApi("/stats/repair-success"),
        fetchApi("/prompts/versions"),
        fetchApi("/review-queue"),
        fetchApi("/breaches?limit=12"),
        fetchApi("/llm/traces?limit=20"),
        fetchApi("/eval/latest"),
      ]);
      setOverview(ov);
      setFailures(fr);
      setRepairs(rp);
      setPrompts(pr);
      setReviewQueue(rq);
      setBreaches(br);
      setTraces(lt);
      setEvalResults(ev);
      setError(null);
      setNeedsAuth(false);
    } catch (e) {
      if (e.status === 401) {
        setNeedsAuth(true);
        setError("Dashboard token required. Enter DASHBOARD_AUTH_TOKEN.");
        return;
      }
      setError(e.message);
    }
  }

  useEffect(() => {
    load();
    const interval = setInterval(load, 30000);
    return () => clearInterval(interval);
  }, []);

  async function openDetail(recordKey) {
    if (!recordKey) return;
    try {
      const data = await fetchApi(`/records/${encodeURIComponent(recordKey)}`);
      setDetail(data);
    } catch (e) {
      setError(e.message);
    }
  }

  async function decideReview(id, status) {
    try {
      await fetchApi(`/review-queue/${id}`, {
        method: "PATCH",
        body: JSON.stringify({
          status,
          resolved_by: "dashboard",
          human_label: status,
        }),
      });
      setReviewQueue((prev) =>
        prev.map((item) => (item.id === id ? { ...item, status, human_label: status } : item))
      );
      if (detail?.review?.id === id) {
        setDetail({ ...detail, review: { ...detail.review, status, human_label: status } });
      }
    } catch (e) {
      setError(e.message);
    }
  }

  const failureChart = failures.slice(0, 8).map((f) => ({
    name: f.rule_name?.replace(/_/g, " ").slice(0, 16) || "unknown",
    failures: Number(f.failures),
  }));

  const sla = overview?.sla;
  const openReviews = reviewQueue.filter((r) => r.status === "open").length;
  const diffs = repairDiff(detail?.repair?.original_record, detail?.repair?.repaired_record);

  return (
    <div className="app">
      <header>
        <div>
          <h1>DataSentinel</h1>
          <p>Agentic data quality platform — live pipeline health</p>
        </div>
        <span className="badge">Rolling 24h window</span>
      </header>

      {needsAuth && (
        <form
          className="auth-form"
          onSubmit={(e) => {
            e.preventDefault();
            setAuthToken(tokenInput.trim());
            setNeedsAuth(false);
            setError(null);
            load();
          }}
        >
          <label htmlFor="ds-token">Dashboard token</label>
          <input
            id="ds-token"
            type="password"
            value={tokenInput}
            onChange={(e) => setTokenInput(e.target.value)}
            placeholder="DASHBOARD_AUTH_TOKEN"
            autoComplete="off"
          />
          <button type="submit">Continue</button>
        </form>
      )}

      {error && !needsAuth && (
        <div className="error">
          Failed to load dashboard: {error}. Start the API: <code>npm run dashboard:api</code>
        </div>
      )}

      {sla && (
        <div className={`sla-banner ${sla.breached ? "sla-breach" : "sla-ok"}`}>
          <div>
            <strong>{sla.headline}</strong>
            {sla.ok_detail && (
              <div className="sla-ok-line">{sla.ok_detail}</div>
            )}
          </div>
          <span>{sla.total_count} records in 24h</span>
        </div>
      )}

      {overview && (
        <div className="grid">
          <StatCard title="Contract Breaches" value={overview.breaches_24h} sub={`${overview.unique_rules_24h} unique rules`} />
          <StatCard title="Records Triaged" value={overview.triaged_24h} sub={`Avg confidence ${overview.avg_confidence_24h}`} />
          <StatCard title="Repair Success" value={`${overview.repair_success_rate_24h}%`} sub={`${overview.repairs_24h} attempts`} />
          <StatCard
            title="Failure rate"
            value={`${sla?.failure_rate_pct ?? 0}%`}
            sub={`Budget ${sla?.max_failure_rate_pct ?? 2}%`}
            tone={sla?.failure_rate_breached ? "danger" : "success"}
          />
          <StatCard
            title="Validation p95"
            value={`${sla?.p95_latency_ms ?? 0}ms`}
            sub={`Budget ${sla?.p95_budget_ms ?? 500}ms`}
            tone={sla?.latency_breached ? "danger" : "success"}
          />
          {evalResults?.available && (
            <StatCard
              title="Eval Accuracy"
              value={`${(evalResults.results.classification_accuracy * 100).toFixed(1)}%`}
              sub={`Repair ${(evalResults.results.repair_accuracy * 100).toFixed(1)}%`}
            />
          )}
        </div>
      )}

      <div className="two-col">
        <div className="section card">
          <h2>Failure Rate by Rule</h2>
          <div className="chart-wrap">
            {failureChart.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={failureChart}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e2a38" />
                  <XAxis dataKey="name" tick={{ fill: "#8b9cb3", fontSize: 11 }} />
                  <YAxis tick={{ fill: "#8b9cb3", fontSize: 11 }} />
                  <Tooltip contentStyle={{ background: "#121820", border: "1px solid #1e2a38" }} />
                  <Bar dataKey="failures" fill="#3b82f6" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <p style={{ color: "#8b9cb3" }}>No breach data yet. Run <code>python scripts/seed_demo.py</code>.</p>
            )}
          </div>
        </div>

        <div className="section card">
          <h2>Human Review Queue</h2>
          <p style={{ color: "#8b9cb3", fontSize: "0.875rem" }}>
            Open: {openReviews} · click a row for the record
          </p>
          <table>
            <thead>
              <tr>
                <th>Class</th>
                <th>Rule</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {reviewQueue.slice(0, 8).map((r) => (
                <tr
                  key={r.id}
                  className={r.record_key ? "clickable" : ""}
                  onClick={() => r.record_key && openDetail(r.record_key)}
                >
                  <td>{r.failure_class}</td>
                  <td>{r.rule_violated || "—"}</td>
                  <td className={r.status === "open" ? "status-open" : "status-resolved"}>{r.status}</td>
                  <td>
                    {r.status === "open" && (
                      <>
                        <button
                          className="resolve-btn"
                          onClick={(e) => {
                            e.stopPropagation();
                            decideReview(r.id, "accepted");
                          }}
                        >
                          Accept
                        </button>{" "}
                        <button
                          className="resolve-btn"
                          onClick={(e) => {
                            e.stopPropagation();
                            decideReview(r.id, "rejected");
                          }}
                        >
                          Reject
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
              {reviewQueue.length === 0 && (
                <tr><td colSpan={4} style={{ color: "#8b9cb3" }}>No review items</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="section card">
        <h2>Recent Breaches</h2>
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>Rule</th>
              <th>Field</th>
              <th>Record</th>
            </tr>
          </thead>
          <tbody>
            {breaches.map((b, i) => (
              <tr
                key={`${b.record_key}-${i}`}
                className={b.record_key ? "clickable" : ""}
                onClick={() => b.record_key && openDetail(b.record_key)}
              >
                <td>{b.time ? new Date(b.time).toLocaleTimeString() : "—"}</td>
                <td>{b.rule_name}</td>
                <td>{b.field_name || "—"}</td>
                <td className="mono">{b.record_key || "—"}</td>
              </tr>
            ))}
            {breaches.length === 0 && (
              <tr><td colSpan={4} style={{ color: "#8b9cb3" }}>No breaches. Run the producer or <code>python scripts/seed_demo.py</code>.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {detail && (
        <div className="section card detail-panel">
          <div className="detail-head">
            <h2>Record {detail.record_key}</h2>
            <button className="resolve-btn" onClick={() => setDetail(null)}>Close</button>
          </div>
          {detail.triage && (
            <p className="sub">
              {detail.triage.failure_class} · {detail.triage.confidence} · {detail.triage.classifier_source}
              {" — "}{detail.triage.explanation}
            </p>
          )}
          {detail.review?.status === "open" && detail.review.id && (
            <p>
              <button className="resolve-btn" onClick={() => decideReview(detail.review.id, "accepted")}>Accept</button>{" "}
              <button className="resolve-btn" onClick={() => decideReview(detail.review.id, "rejected")}>Reject</button>
            </p>
          )}
          <div className="two-col">
            <div>
              <h3>Raw record</h3>
              <pre>{JSON.stringify(detail.record, null, 2)}</pre>
            </div>
            <div>
              <h3>Repair diff</h3>
              {diffs.length > 0 ? (
                <table>
                  <thead>
                    <tr><th>Field</th><th>From</th><th>To</th></tr>
                  </thead>
                  <tbody>
                    {diffs.map((d) => (
                      <tr key={d.field}>
                        <td>{d.field}</td>
                        <td>{String(d.from)}</td>
                        <td>{String(d.to)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p style={{ color: "#8b9cb3" }}>No repair on this record.</p>
              )}
              <h3>Good samples</h3>
              <pre>{JSON.stringify(detail.good_samples?.slice(0, 2) || [], null, 2)}</pre>
            </div>
          </div>
        </div>
      )}

      <div className="two-col">
        <div className="section card">
          <h2>Prompt Versions</h2>
          <table>
            <thead>
              <tr>
                <th>Agent</th>
                <th>Version</th>
                <th>Accuracy</th>
                <th>Active</th>
              </tr>
            </thead>
            <tbody>
              {prompts.map((p) => (
                <tr key={p.prompt_id}>
                  <td>{p.agent_name}</td>
                  <td>v{p.version}</td>
                  <td>{p.accuracy != null ? `${(p.accuracy * 100).toFixed(1)}%` : "—"}</td>
                  <td>{p.is_active ? "yes" : ""}</td>
                </tr>
              ))}
              {prompts.length === 0 && (
                <tr><td colSpan={4} style={{ color: "#8b9cb3" }}>Run triage with --seed-prompts</td></tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="section card">
          <h2>Repair Success</h2>
          <table>
            <thead>
              <tr>
                <th>Field</th>
                <th>Validated</th>
                <th>Routed</th>
                <th>Count</th>
              </tr>
            </thead>
            <tbody>
              {repairs.map((r, i) => (
                <tr key={i}>
                  <td>{r.field_repaired || "—"}</td>
                  <td>{r.validation_passed ? "yes" : "no"}</td>
                  <td>{r.routed_to_repaired ? "yes" : "no"}</td>
                  <td>{r.count}</td>
                </tr>
              ))}
              {repairs.length === 0 && (
                <tr><td colSpan={4} style={{ color: "#8b9cb3" }}>No repair attempts yet</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="section card">
        <h2>LLM Traces</h2>
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>Agent</th>
              <th>Model</th>
              <th>Latency</th>
              <th>Tokens</th>
              <th>Cost</th>
            </tr>
          </thead>
          <tbody>
            {traces.map((t, i) => (
              <tr key={i}>
                <td>{new Date(t.time).toLocaleTimeString()}</td>
                <td>{t.agent_name}</td>
                <td>{t.model}</td>
                <td>{t.latency_ms?.toFixed(0)}ms</td>
                <td>{(t.input_tokens || 0) + (t.output_tokens || 0)}</td>
                <td>${(t.cost_usd || 0).toFixed(6)}</td>
              </tr>
            ))}
            {traces.length === 0 && (
              <tr><td colSpan={6} style={{ color: "#8b9cb3" }}>No LLM traces yet. Run triage service.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

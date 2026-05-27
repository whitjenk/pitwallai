<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>PitWallAI — Radio Intercept Decoder</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet" />
  <script crossorigin src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
  <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
  <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
  <script src="https://unpkg.com/recharts@2.12.7/umd/Recharts.js"></script>
  <style>
    * { box-sizing: border-box; }
    body { margin: 0; font-family: Inter, system-ui, sans-serif; background: #080a0e; color: #e6edf3; }
    .font-mono { font-family: "JetBrains Mono", monospace; }
    @keyframes pulse-border { 0%, 100% { border-color: #d29922; } 50% { border-color: #FF8000; } }
    .pulse-amber { animation: pulse-border 1.2s ease-in-out infinite; }
    @keyframes slide-in { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: translateY(0); } }
    .slide-in { animation: slide-in 0.2s ease-out; }
    @keyframes pulse-red { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
    .pulse-critical { animation: pulse-red 0.8s ease-in-out infinite; }
    .feed-scroll { mask-image: linear-gradient(to bottom, transparent, black 12%, black 88%, transparent); }
  </style>
</head>
<body>
  <div id="root"></div>
  <script type="text/babel" data-presets="react">
    const { useState, useEffect, useRef, useMemo, useCallback } = React;
    const {
      RadialBarChart, RadialBar, PieChart, Pie, Cell, ResponsiveContainer
    } = Recharts;

    const COLORS = {
      bg: "#080a0e",
      surface: "#0d1117",
      elevated: "#161b22",
      border: "#21262d",
      text: "#e6edf3",
      muted: "#8b949e",
      orange: "#FF8000",
      green: "#3fb950",
      amber: "#d29922",
      red: "#f85149",
      blue: "#58a6ff",
    };

    const TEAM_COLORS = {
      VER: "#3671C6", HAM: "#27F4D2", NOR: "#FF8000", PIA: "#FF8000",
      LEC: "#E8002D", SAI: "#E8002D", RUS: "#27F4D2", ALO: "#229971",
    };

    const URGENCY_STYLES = {
      LOW: { bg: "#21262d", text: "#8b949e", label: "LOW" },
      MEDIUM: { bg: "#1c3a5e", text: COLORS.blue, label: "MEDIUM" },
      HIGH: { bg: "#3d2e00", text: COLORS.amber, label: "HIGH" },
      CRITICAL: { bg: "#3d1214", text: COLORS.red, label: "CRITICAL" },
    };

    const PIE_COLORS = ["#FF8000", "#58a6ff", "#3fb950", "#d29922", "#f85149", "#8b949e", "#E8002D", "#3671C6"];

    function urgencyClass(level) {
      if (level === "CRITICAL") return "pulse-critical";
      return "";
    }

    function App() {
      const [transmissions, setTransmissions] = useState([]);
      const [intelItems, setIntelItems] = useState([]);
      const [actedOn, setActedOn] = useState([]);
      const [session, setSession] = useState({ mode: "rehearsal", session_key: 0, circuit: "—", transmission_count: 0 });
      const [wsStatus, setWsStatus] = useState("connecting");
      const [latencyFlash, setLatencyFlash] = useState(false);
      const [lastLatency, setLastLatency] = useState(0);
      const [rehearsalModal, setRehearsalModal] = useState(null);
      const [rehearsalProgress, setRehearsalProgress] = useState({});
      const [rehearsalSpeed, setRehearsalSpeed] = useState(3);
      const [utcClock, setUtcClock] = useState(new Date());
      const [evidenceLog, setEvidenceLog] = useState([]);
      const wsRef = useRef(null);

      useEffect(() => {
        const t = setInterval(() => setUtcClock(new Date()), 1000);
        return () => clearInterval(t);
      }, []);

      const connectWs = useCallback(() => {
        const port = window.location.port || "8000";
        const proto = window.location.protocol === "https:" ? "wss" : "ws";
        const ws = new WebSocket(`${proto}://${window.location.hostname}:${port}/ws/stream`);
        wsRef.current = ws;
        setWsStatus("connecting");

        ws.onopen = () => setWsStatus("connected");
        ws.onclose = () => {
          setWsStatus("disconnected");
          setTimeout(connectWs, 2000);
        };
        ws.onerror = () => setWsStatus("error");

        ws.onmessage = (msg) => {
          const event = JSON.parse(msg.data);
          const type = event.event_type;
          const payload = event.payload;

          if (type === "SYSTEM_STATUS") {
            setSession((s) => ({ ...s, ...payload, mode: payload.mode || s.mode }));
            if (payload.rehearsal_progress) setRehearsalProgress(payload.rehearsal_progress);
            return;
          }

          if (type === "TRANSMISSION_DECODED") {
            const tx = payload;
            setTransmissions((prev) => [tx, ...prev].slice(0, 50));
            setLastLatency(tx.processing_latency_ms || 0);
            if (tx.evidence_summary) {
              setEvidenceLog((prev) => [{
                text: tx.evidence_summary,
                driver: tx.driver_code,
                lap: tx.lap_number,
              }, ...prev].slice(0, 5));
            }
            if (tx.competitor_intel && tx.competitor_intel.confirmation_state === "UNCONFIRMED") {
              setIntelItems((prev) => {
                const exists = prev.find((i) => i.transmission_id === tx.transmission_id);
                if (exists) return prev;
                return [{ ...tx, intel: tx.competitor_intel }, ...prev];
              });
            }
            return;
          }

          if (type === "COMPETITOR_INTEL_UNCONFIRMED") {
            const tx = payload;
            setIntelItems((prev) => {
              if (prev.find((i) => i.transmission_id === tx.transmission_id)) return prev;
              return [{ ...tx, intel: tx.competitor_intel }, ...prev];
            });
            return;
          }

          if (type === "LATENCY_BREACH") {
            setLatencyFlash(true);
            setTimeout(() => setLatencyFlash(false), 2000);
            return;
          }

          if (type === "REHEARSAL_COMPLETE") {
            setRehearsalModal(payload);
            return;
          }
        };
      }, []);

      useEffect(() => {
        connectWs();
        return () => { if (wsRef.current) wsRef.current.close(); };
      }, [connectWs]);

      useEffect(() => {
        const poll = setInterval(async () => {
          try {
            const res = await fetch("/api/session/status");
            const data = await res.json();
            setSession((s) => ({ ...s, ...data }));
            if (data.rehearsal_progress) setRehearsalProgress(data.rehearsal_progress);
          } catch (_) {}
        }, 3000);
        return () => clearInterval(poll);
      }, []);

      const confirmIntel = async (transmissionId, state) => {
        const res = await fetch(`/api/intel/confirm/${transmissionId}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ state }),
        });
        const updated = await res.json();
        if (state === "ACTED_ON") {
          setIntelItems((prev) => prev.filter((i) => i.transmission_id !== transmissionId));
          setActedOn((prev) => [updated, ...prev].slice(0, 10));
        } else {
          setIntelItems((prev) =>
            prev.map((i) =>
              i.transmission_id === transmissionId
                ? { ...i, intel: { ...i.intel, confirmation_state: "ACKNOWLEDGED" } }
                : i
            )
          );
        }
      };

      const startRehearsal = async () => {
        await fetch("/api/rehearsal/start", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ scenario: "monaco_2024" }),
        });
      };

      const stopRehearsal = async () => {
        await fetch("/api/rehearsal/stop", { method: "POST" });
      };

      const avgLatency = useMemo(() => {
        const recent = transmissions.slice(0, 10);
        const vals = recent.map((t) => t.processing_latency_ms).filter(Boolean);
        return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : 0;
      }, [transmissions]);

      const intentCounts = useMemo(() => {
        const counts = {};
        transmissions.forEach((t) => {
          const k = t.decoded_intent || "UNKNOWN";
          counts[k] = (counts[k] || 0) + 1;
        });
        return Object.entries(counts).map(([name, value]) => ({ name, value }));
      }, [transmissions]);

      const urgencyCounts = useMemo(() => {
        const c = { LOW: 0, MEDIUM: 0, HIGH: 0, CRITICAL: 0 };
        transmissions.forEach((t) => { if (c[t.urgency_level] !== undefined) c[t.urgency_level]++; });
        return c;
      }, [transmissions]);

      const signals = useMemo(() =>
        transmissions
          .filter((t) => t.strategic_signal && t.strategic_signal !== "NEUTRAL" && t.strategic_signal !== "UNKNOWN")
          .slice(0, 6),
      [transmissions]);

      const statusDot = wsStatus === "connected" ? COLORS.green : wsStatus === "connecting" ? COLORS.amber : COLORS.red;

      return (
        <div className="min-h-screen flex flex-col" style={{ background: COLORS.bg }}>
          {/* Top bar */}
          <header className="flex items-center justify-between px-5 py-3 border-b" style={{ borderColor: COLORS.border, background: COLORS.surface }}>
            <div className="flex items-center gap-3">
              <span className="text-lg font-bold text-white">PITWALLAI</span>
              <span className="text-sm font-semibold" style={{ color: COLORS.orange }}>RADIO INTERCEPT DECODER</span>
            </div>
            <div className="flex items-center gap-4 text-sm" style={{ color: COLORS.muted }}>
              <span>Session {session.session_key || "—"}</span>
              <span>{session.circuit || "—"}</span>
              <span className="px-2 py-0.5 rounded text-xs font-mono uppercase" style={{ background: COLORS.elevated, color: COLORS.orange }}>
                {session.mode || "rehearsal"}
              </span>
            </div>
            <div className="flex items-center gap-4 text-sm">
              <span className="font-mono">{transmissions.length} tx</span>
              <span className="w-2.5 h-2.5 rounded-full" style={{ background: statusDot }} title={wsStatus} />
              <span className="font-mono text-xs" style={{ color: COLORS.muted }}>
                {utcClock.toISOString().slice(11, 19)} UTC
              </span>
            </div>
          </header>

          <main className="flex-1 grid grid-cols-12 gap-3 p-3 min-h-0">
            {/* Left — Radio Feed */}
            <section className="col-span-3 flex flex-col rounded-lg border overflow-hidden" style={{ background: COLORS.surface, borderColor: COLORS.border }}>
              <h2 className="text-xs font-semibold tracking-wider px-3 py-2 border-b" style={{ color: COLORS.muted, borderColor: COLORS.border }}>
                RADIO INTERCEPT FEED
              </h2>
              <div className="flex-1 overflow-hidden feed-scroll p-2 space-y-2">
                {transmissions.slice(0, 8).map((tx, i) => (
                  <FeedCard key={tx.transmission_id || i} tx={tx} />
                ))}
                {transmissions.length === 0 && (
                  <p className="text-xs text-center py-8" style={{ color: COLORS.muted }}>Awaiting transmissions…</p>
                )}
              </div>
            </section>

            {/* Center — Strategic Board */}
            <section className="col-span-5 flex flex-col gap-3 min-h-0">
              <div className="rounded-lg border p-3" style={{ background: COLORS.surface, borderColor: COLORS.border }}>
                <h2 className="text-xs font-semibold tracking-wider mb-2" style={{ color: COLORS.muted }}>STRATEGIC INTELLIGENCE BOARD</h2>
                <div className="grid grid-cols-2 gap-2">
                  {signals.map((tx, i) => (
                    <div key={i} className="rounded p-2 text-xs border" style={{ background: COLORS.elevated, borderColor: COLORS.border }}>
                      <div className="font-mono font-semibold" style={{ color: TEAM_COLORS[tx.driver_code] || tx.team_color || COLORS.orange }}>
                        {tx.strategic_signal}
                      </div>
                      <div style={{ color: COLORS.muted }}>{tx.driver_code} · {tx.team}</div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="rounded-lg border p-3 flex-1 overflow-auto" style={{ background: COLORS.surface, borderColor: COLORS.border }}>
                <h2 className="text-xs font-semibold tracking-wider mb-3" style={{ color: COLORS.orange }}>COMPETITOR INTEL PANEL</h2>
                <div className="space-y-3">
                  {intelItems.map((item) => (
                    <IntelCard
                      key={item.transmission_id}
                      item={item}
                      onConfirm={confirmIntel}
                    />
                  ))}
                  {intelItems.length === 0 && (
                    <p className="text-xs" style={{ color: COLORS.muted }}>No unconfirmed competitor intel.</p>
                  )}
                </div>
              </div>

              <div className="rounded-lg border p-3" style={{ background: COLORS.surface, borderColor: COLORS.border }}>
                <h2 className="text-xs font-semibold tracking-wider mb-2" style={{ color: COLORS.green }}>SESSION TIMELINE (ACTED ON)</h2>
                <div className="space-y-2">
                  {actedOn.map((tx) => (
                    <div key={tx.transmission_id} className="rounded p-2 text-xs border-l-2" style={{ borderColor: COLORS.green, background: COLORS.elevated }}>
                      <span className="font-mono font-semibold" style={{ color: TEAM_COLORS[tx.driver_code] || COLORS.green }}>
                        {tx.competitor_intel?.target_driver_code || tx.driver_code}
                      </span>
                      <span style={{ color: COLORS.muted }}> — {tx.competitor_intel?.inferred_action}</span>
                    </div>
                  ))}
                </div>
              </div>
            </section>

            {/* Right — Metrics */}
            <section className="col-span-4 flex flex-col gap-3">
              <div className={`rounded-lg border p-3 ${latencyFlash ? "ring-2 ring-red-500" : ""}`} style={{ background: COLORS.surface, borderColor: COLORS.border }}>
                <h2 className="text-xs font-semibold tracking-wider mb-1" style={{ color: COLORS.muted }}>LATENCY GAUGE</h2>
                <LatencyGauge value={lastLatency} avg={avgLatency} flash={latencyFlash} />
              </div>

              <div className="rounded-lg border p-3" style={{ background: COLORS.surface, borderColor: COLORS.border }}>
                <h2 className="text-xs font-semibold tracking-wider mb-1" style={{ color: COLORS.muted }}>INTENT DISTRIBUTION</h2>
                <div style={{ height: 140 }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie data={intentCounts} dataKey="value" nameKey="name" cx="50%" cy="50%" innerRadius={35} outerRadius={55}>
                        {intentCounts.map((_, i) => (
                          <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                        ))}
                      </Pie>
                    </PieChart>
                  </ResponsiveContainer>
                </div>
              </div>

              <div className="rounded-lg border p-3" style={{ background: COLORS.surface, borderColor: COLORS.border }}>
                <h2 className="text-xs font-semibold tracking-wider mb-2" style={{ color: COLORS.muted }}>URGENCY COUNTERS</h2>
                <div className="flex gap-2 flex-wrap">
                  {Object.entries(urgencyCounts).map(([level, count]) => (
                    <span key={level} className="px-2 py-1 rounded text-xs font-mono font-semibold"
                      style={{ background: URGENCY_STYLES[level]?.bg, color: URGENCY_STYLES[level]?.text }}>
                      {level}: {count}
                    </span>
                  ))}
                </div>
              </div>

              {session.mode === "rehearsal" && (
                <div className="rounded-lg border p-3" style={{ background: COLORS.surface, borderColor: COLORS.border }}>
                  <h2 className="text-xs font-semibold tracking-wider mb-2" style={{ color: COLORS.orange }}>REHEARSAL CONTROLS</h2>
                  <p className="text-xs mb-2" style={{ color: COLORS.muted }}>
                    monaco_2024 · Lap {rehearsalProgress.current_lap || session.current_lap || "—"}
                  </p>
                  <div className="w-full h-1.5 rounded mb-3" style={{ background: COLORS.elevated }}>
                    <div className="h-full rounded" style={{
                      width: `${((rehearsalProgress.current_event || 0) / (rehearsalProgress.total_events || 12)) * 100}%`,
                      background: COLORS.orange,
                    }} />
                  </div>
                  <div className="flex gap-1 mb-2">
                    {[1, 3, 5].map((s) => (
                      <button key={s} onClick={() => setRehearsalSpeed(s)}
                        className="px-2 py-1 text-xs font-mono rounded"
                        style={{ background: rehearsalSpeed === s ? COLORS.orange : COLORS.elevated, color: rehearsalSpeed === s ? "#000" : COLORS.muted }}>
                        {s}x
                      </button>
                    ))}
                  </div>
                  <div className="flex gap-2">
                    <button onClick={startRehearsal} className="flex-1 py-1.5 text-xs font-semibold rounded" style={{ background: COLORS.green, color: "#000" }}>LOAD</button>
                    <button onClick={stopRehearsal} className="flex-1 py-1.5 text-xs font-semibold rounded" style={{ background: COLORS.red, color: "#fff" }}>STOP</button>
                    <button onClick={startRehearsal} className="flex-1 py-1.5 text-xs font-semibold rounded" style={{ background: COLORS.blue, color: "#000" }}>REPLAY</button>
                  </div>
                </div>
              )}

              <div className="rounded-lg border p-3 flex-1" style={{ background: "#050608", borderColor: COLORS.border }}>
                <h2 className="text-xs font-semibold tracking-wider mb-2" style={{ color: COLORS.green }}>EVIDENCE LOG</h2>
                <div className="space-y-2 font-mono text-xs" style={{ color: COLORS.green }}>
                  {evidenceLog.map((e, i) => (
                    <div key={i} className="border-l-2 pl-2" style={{ borderColor: COLORS.green }}>
                      <span style={{ color: COLORS.muted }}>[{e.driver} L{e.lap || "?"}] </span>
                      {e.text}
                    </div>
                  ))}
                </div>
              </div>
            </section>
          </main>

          {rehearsalModal && (
            <div className="fixed inset-0 flex items-center justify-center z-50" style={{ background: "rgba(0,0,0,0.75)" }}>
              <div className="rounded-lg p-6 max-w-md border" style={{ background: COLORS.elevated, borderColor: COLORS.orange }}>
                <h3 className="text-lg font-bold mb-3" style={{ color: COLORS.orange }}>Rehearsal Complete</h3>
                <pre className="text-xs font-mono whitespace-pre-wrap" style={{ color: COLORS.text }}>
                  {JSON.stringify(rehearsalModal, null, 2)}
                </pre>
                <button onClick={() => setRehearsalModal(null)} className="mt-4 px-4 py-2 rounded text-sm font-semibold" style={{ background: COLORS.orange, color: "#000" }}>
                  Dismiss
                </button>
              </div>
            </div>
          )}
        </div>
      );
    }

    function FeedCard({ tx }) {
      const urg = URGENCY_STYLES[tx.urgency_level] || URGENCY_STYLES.LOW;
      const lat = tx.processing_latency_ms || 0;
      const latColor = lat < 800 ? COLORS.green : COLORS.red;
      const driverColor = tx.team_color || TEAM_COLORS[tx.driver_code] || COLORS.orange;

      return (
        <div className="slide-in rounded p-2 border text-xs" style={{ background: COLORS.elevated, borderColor: COLORS.border }}>
          <div className="flex justify-between items-start mb-1">
            <span className="text-xl font-bold font-mono" style={{ color: driverColor }}>{tx.driver_code}</span>
            <span className={`px-1.5 py-0.5 rounded text-[10px] font-mono font-semibold ${urgencyClass(tx.urgency_level)}`}
              style={{ background: urg.bg, color: urg.text }}>{tx.decoded_intent}</span>
          </div>
          <div style={{ color: COLORS.muted }} className="mb-1">{tx.team}</div>
          <p className="italic line-clamp-2 mb-2" style={{ color: COLORS.text }}>{tx.raw_transcript}</p>
          <div className="w-full h-1 rounded mb-1" style={{ background: COLORS.border }}>
            <div className="h-full rounded" style={{ width: `${(tx.confidence_score || 0) * 100}%`, background: COLORS.blue }} />
          </div>
          <div className="flex flex-wrap gap-1 mb-1">
            {(tx.jargon_decoded || []).slice(0, 3).map((j, i) => (
              <span key={i} className="px-1 py-0.5 rounded text-[9px] font-mono" style={{ background: COLORS.surface, color: COLORS.amber }}>
                {j.term} → {j.plain_english?.slice(0, 20)}
              </span>
            ))}
          </div>
          <div className="flex justify-between font-mono text-[10px]" style={{ color: COLORS.muted }}>
            <span>Lap {tx.lap_number || "—"}</span>
            <span style={{ color: latColor }}>{Math.round(lat)}ms</span>
          </div>
        </div>
      );
    }

    function IntelCard({ item, onConfirm }) {
      const intel = item.intel || item.competitor_intel;
      const isAck = intel?.confirmation_state === "ACKNOWLEDGED";
      const targetColor = TEAM_COLORS[intel?.target_driver_code] || COLORS.amber;
      const pct = Math.round((intel?.reliability_score || 0) * 100);

      return (
        <div className={`rounded p-3 border-2 ${!isAck ? "pulse-amber" : ""}`}
          style={{ background: COLORS.elevated, borderColor: isAck ? COLORS.blue : COLORS.amber }}>
          <div className="flex justify-between items-center mb-2">
            <span className="text-lg font-bold font-mono" style={{ color: targetColor }}>
              {intel?.target_driver_code || "?"}
            </span>
            <span className="text-xs font-mono" style={{ color: COLORS.muted }}>{intel?.target_team}</span>
          </div>
          <p className="text-sm mb-2">{intel?.inferred_action}</p>
          <div className="flex items-center gap-2 mb-2">
            <div className="w-10 h-10 rounded-full flex items-center justify-center text-xs font-mono font-bold border-2"
              style={{ borderColor: COLORS.amber, color: COLORS.amber }}>{pct}%</div>
            <p className="text-xs italic flex-1" style={{ color: COLORS.muted }}>{intel?.evidence_transcript}</p>
          </div>
          {!isAck && (
            <div className="flex gap-2">
              <button onClick={() => onConfirm(item.transmission_id, "ACKNOWLEDGED")}
                className="flex-1 py-1 text-xs font-semibold rounded" style={{ background: COLORS.blue, color: "#000" }}>ACK</button>
              <button onClick={() => onConfirm(item.transmission_id, "ACTED_ON")}
                className="flex-1 py-1 text-xs font-semibold rounded" style={{ background: COLORS.green, color: "#000" }}>ACTED ON</button>
            </div>
          )}
        </div>
      );
    }

    function LatencyGauge({ value, avg, flash }) {
      const color = value < 800 ? COLORS.green : value < 1200 ? COLORS.amber : COLORS.red;
      const data = [{ name: "latency", value: Math.min(value, 2000), fill: flash ? COLORS.red : color }];
      return (
        <div style={{ height: 160 }}>
          <ResponsiveContainer width="100%" height="100%">
            <RadialBarChart cx="50%" cy="50%" innerRadius="55%" outerRadius="90%" data={data} startAngle={180} endAngle={0}>
              <RadialBar background dataKey="value" cornerRadius={6} />
            </RadialBarChart>
          </ResponsiveContainer>
          <div className="text-center -mt-16">
            <div className="text-2xl font-mono font-bold" style={{ color: flash ? COLORS.red : color }}>{Math.round(value)}ms</div>
            <div className="text-xs" style={{ color: COLORS.muted }}>10-tx avg: {Math.round(avg)}ms</div>
          </div>
        </div>
      );
    }

    const root = ReactDOM.createRoot(document.getElementById("root"));
    root.render(<App />);
  </script>
</body>
</html>

/**
 * MonacoTrackMap — schematic Circuit de Monaco with driver dots and radio pins.
 * Embed this component definition inside dashboard.jsx (Babel standalone).
 */

const MONACO_WAYPOINTS = [
  [30, 110], [40, 80], [55, 55], [80, 40], [110, 35], [140, 38], [165, 50],
  [180, 65], [185, 85], [178, 105], [160, 115], [148, 125], [150, 140],
  [162, 155], [170, 170], [165, 185], [150, 195], [130, 200], [110, 198],
  [95, 190], [85, 178], [78, 162], [72, 148], [60, 138], [42, 130], [30, 118],
];

const DRIVER_OFFSETS = {
  NOR: 0.0,
  PIA: 0.15,
  VER: 0.3,
  LEC: 0.45,
  HAM: 0.6,
  RUS: 0.75,
};

const PIN_COLORS = {
  LOW: "#484f58",
  MEDIUM: "#58a6ff",
  HIGH: "#d29922",
  CRITICAL: "#f85149",
};

function getPositionOnPath(lapFraction, driverOffset = 0) {
  const t = ((lapFraction + driverOffset) % 1 + 1) % 1;
  const pts = MONACO_WAYPOINTS;
  const segCount = pts.length - 1;
  const scaled = t * segCount;
  const idx = Math.floor(scaled) % segCount;
  const frac = scaled - Math.floor(scaled);
  const [x1, y1] = pts[idx];
  const [x2, y2] = pts[idx + 1];
  return { x: x1 + (x2 - x1) * frac, y: y1 + (y2 - y1) * frac };
}

function MonacoTrackMap({ transmissions = [], driverPositions = {}, mode = "rehearsal", currentLap = 34, teamColors = {} }) {
  const [pins, setPins] = React.useState([]);
  const [hovered, setHovered] = React.useState(null);
  const [tooltip, setTooltip] = React.useState(null);
  const pinIdRef = React.useRef(0);

  const pathD = `M ${MONACO_WAYPOINTS.map(([x, y]) => `${x},${y}`).join(" L ")} Z`;

  const lapFraction = Math.min(1, Math.max(0, (currentLap - 34) / 6));

  const computedPositions = React.useMemo(() => {
    if (driverPositions && Object.keys(driverPositions).length > 0) {
      return driverPositions;
    }
    const pos = {};
    Object.entries(DRIVER_OFFSETS).forEach(([code, offset]) => {
      pos[code] = getPositionOnPath(lapFraction, offset);
    });
    return pos;
  }, [driverPositions, lapFraction]);

  React.useEffect(() => {
    const latest = transmissions[0];
    if (!latest || !latest.driver_code) return;

    const pos = computedPositions[latest.driver_code] || getPositionOnPath(lapFraction, DRIVER_OFFSETS[latest.driver_code] || 0);
    const urgency = latest.urgency_level || "LOW";
    const id = `pin-${pinIdRef.current++}`;

    const lifetimeMs = urgency === "CRITICAL" ? null : urgency === "HIGH" ? 20000 : 8000;

    setPins((prev) => {
      const next = [
        {
          id,
          x: pos.x,
          y: pos.y,
          urgency,
          transcript: latest.raw_transcript,
          driver: latest.driver_code,
          intent: latest.decoded_intent,
          clicked: false,
          createdAt: Date.now(),
        },
        ...prev,
      ];
      const capped = next.filter((p) => p.urgency === "CRITICAL" || !p.clicked).slice(0, 12);
      return capped;
    });

    if (lifetimeMs) {
      const timer = setTimeout(() => {
        setPins((prev) => prev.filter((p) => p.id !== id));
      }, lifetimeMs);
      return () => clearTimeout(timer);
    }
  }, [transmissions, computedPositions, lapFraction]);

  React.useEffect(() => {
    const interval = setInterval(() => {
      const now = Date.now();
      setPins((prev) => {
        let next = prev.filter((p) => {
          if (p.urgency === "CRITICAL") return true;
          if (p.urgency === "HIGH") return now - p.createdAt < 20000;
          return now - p.createdAt < 8000;
        });
        if (next.length > 12) {
          const critical = next.filter((p) => p.urgency === "CRITICAL");
          const rest = next.filter((p) => p.urgency !== "CRITICAL");
          next = [...critical, ...rest.slice(0, 12 - critical.length)];
        }
        return next;
      });
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  const handlePinClick = (pin) => {
    if (pin.urgency === "CRITICAL") {
      setPins((prev) =>
        prev.map((p) => (p.id === pin.id ? { ...p, clicked: true } : p))
      );
    }
    if (typeof window.sendPrompt === "function") {
      window.sendPrompt(pin.transcript);
    }
  };

  return (
    <div className="rounded-lg border p-2" style={{ background: "#0d1117", borderColor: "#21262d", maxHeight: 240 }}>
      <h2 className="text-xs font-semibold tracking-wider mb-1" style={{ color: "#8b949e" }}>
        MONACO TRACK MAP · {mode.toUpperCase()} · L{currentLap}
      </h2>
      <div style={{ position: "relative", height: 200 }}>
        <svg viewBox="0 0 300 220" width="100%" height="200" style={{ display: "block" }}>
          <rect width="300" height="220" fill="#080a0e" />
          <path d={pathD} fill="none" stroke="#2a3a4a" strokeWidth="8" strokeLinejoin="round" />
          <path d={pathD} fill="none" stroke="#1a2530" strokeWidth="4" strokeLinejoin="round" />
          <line x1="165" y1="50" x2="180" y2="65" stroke="#FF8000" strokeWidth="2" strokeDasharray="4 3" />
          <text x="172" y="52" fill="#FF8000" fontSize="7" fontFamily="Inter, sans-serif">PIT</text>
          <text x="175" y="78" fill="#8b949e" fontSize="7" fontFamily="Inter, sans-serif">TUNNEL</text>
          <text x="148" y="132" fill="#8b949e" fontSize="7" fontFamily="Inter, sans-serif">LOEWS</text>
          <text x="158" y="172" fill="#8b949e" fontSize="7" fontFamily="Inter, sans-serif">POOL</text>
          <text x="90" y="200" fill="#8b949e" fontSize="7" fontFamily="Inter, sans-serif">RASCASSE</text>

          {pins.map((pin) => (
            <g
              key={pin.id}
              onClick={() => handlePinClick(pin)}
              style={{ cursor: "pointer", opacity: pin.clicked ? 0.3 : 1 }}
              className={pin.urgency === "CRITICAL" && !pin.clicked ? "pin-pulse" : "pin-appear"}
            >
              <circle cx={pin.x} cy={pin.y} r="8" fill={PIN_COLORS[pin.urgency] || PIN_COLORS.LOW} opacity="0.85" />
              <circle cx={pin.x} cy={pin.y} r="4" fill={PIN_COLORS[pin.urgency] || PIN_COLORS.LOW} />
            </g>
          ))}

          {Object.entries(computedPositions).map(([code, pos]) => {
            const color = teamColors[code] || "#FF8000";
            return (
              <g
                key={code}
                className="driver-dot"
                onMouseEnter={() => setHovered(code)}
                onMouseLeave={() => { setHovered(null); setTooltip(null); }}
                onMouseMove={(e) => setTooltip({ code, x: e.nativeEvent.offsetX, y: e.nativeEvent.offsetY })}
              >
                <circle cx={pos.x} cy={pos.y} r="5" fill={color} stroke="#fff" strokeWidth="0.5" />
                <text x={pos.x} y={pos.y + 2} textAnchor="middle" fill="#fff" fontSize="5" fontWeight="bold" fontFamily="JetBrains Mono, monospace">
                  {code}
                </text>
              </g>
            );
          })}
        </svg>
        {tooltip && hovered && (
          <div
            className="text-[10px] font-mono px-2 py-1 rounded"
            style={{
              position: "absolute",
              left: tooltip.x + 8,
              top: tooltip.y + 8,
              background: "#161b22",
              border: "1px solid #21262d",
              color: "#e6edf3",
              pointerEvents: "none",
              zIndex: 10,
            }}
          >
            {hovered} · {transmissions.find((t) => t.driver_code === hovered)?.decoded_intent || "—"}
          </div>
        )}
      </div>
      <div className="flex gap-4 mt-1 justify-center" style={{ fontSize: 9, color: "#8b949e" }}>
        <span><span style={{ color: "#FF8000" }}>●</span> McLaren</span>
        <span><span style={{ color: "#2a3a4a" }}>●</span> Track</span>
      </div>
      <style>{`
        .driver-dot { transition: all 0.8s ease; }
        @keyframes pinAppear { from { transform: scale(0); opacity: 0; } to { transform: scale(1); opacity: 1; } }
        .pin-appear { animation: pinAppear 0.3s ease-out; }
        @keyframes pinPulse { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.4); } }
        .pin-pulse { animation: pinAppear 0.3s ease-out, pinPulse 1.5s ease-in-out infinite; transform-origin: center; transform-box: fill-box; }
      `}</style>
    </div>
  );
}

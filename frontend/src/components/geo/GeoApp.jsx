// ─────────────────────────────────────────────────────────────────────────────
// GeoApp.jsx — Geospatial Intelligence Dashboard (No External API)
// Pure CSS/SVG simulation — no Cesium, no Google Maps, no API keys required.
// ─────────────────────────────────────────────────────────────────────────────
import React, { useState, useEffect, useCallback, useRef, useMemo } from "react";
import "./GeoApp.css";

// ── Simulated data generators ───────────────────────────────────────────────
function generateFlights(count = 12) {
  const airlines = ["AI", "UK", "6E", "SG", "EK", "BA", "LH", "AA", "DL", "QF"];
  const routes = [
    { from: "DEL", to: "BOM", lat: 22, lng: 75 },
    { from: "BOM", to: "DXB", lat: 20, lng: 65 },
    { from: "DEL", to: "LHR", lat: 40, lng: 30 },
    { from: "SFO", to: "NRT", lat: 38, lng: -160 },
    { from: "JFK", to: "CDG", lat: 45, lng: -30 },
    { from: "SYD", to: "SIN", lat: -10, lng: 115 },
    { from: "DXB", to: "LHR", lat: 38, lng: 30 },
    { from: "HKG", to: "LAX", lat: 30, lng: -150 },
    { from: "FCO", to: "JFK", lat: 42, lng: -40 },
    { from: "NRT", to: "ICN", lat: 36, lng: 131 },
    { from: "BKK", to: "SYD", lat: -5, lng: 125 },
    { from: "MAD", to: "MEX", lat: 30, lng: -60 },
  ];
  return Array.from({ length: count }, (_, i) => {
    const route = routes[i % routes.length];
    return {
      id: `${airlines[i % airlines.length]}${100 + i}`,
      airline: airlines[i % airlines.length],
      from: route.from,
      to: route.to,
      lat: route.lat + (Math.random() - 0.5) * 6,
      lng: route.lng + (Math.random() - 0.5) * 10,
      alt: 30000 + Math.random() * 12000,
      speed: 450 + Math.random() * 200,
      heading: Math.random() * 360,
    };
  });
}

function generateSatellites(count = 8) {
  const names = ["ISS", "Hubble", "Landsat-9", "Sentinel-2", "GOES-18", "Terra", "Aqua", "NOAA-20"];
  return Array.from({ length: count }, (_, i) => ({
    id: `SAT-${i}`,
    name: names[i % names.length],
    lat: (Math.random() - 0.5) * 140,
    lng: (Math.random() - 0.5) * 340,
    alt: 400 + Math.random() * 35000,
    type: i < 2 ? "manned" : "observation",
  }));
}

function generateShips(count = 10) {
  const types = ["Cargo", "Tanker", "Container", "Fishing", "Military", "Cruise"];
  return Array.from({ length: count }, (_, i) => ({
    id: `SHIP-${i}`,
    name: `${types[i % types.length]} ${1000 + i}`,
    type: types[i % types.length],
    lat: (Math.random() - 0.5) * 120,
    lng: (Math.random() - 0.5) * 300,
    speed: 8 + Math.random() * 20,
    heading: Math.random() * 360,
    ais: Math.random() > 0.15, // 15% "dark ships"
  }));
}

function generateAlerts() {
  return [
    { id: 1, severity: "high", text: "Unusual flight pattern detected — AI-204 deviation", time: "2m ago", type: "anomaly" },
    { id: 2, severity: "medium", text: "Dark ship detected near Strait of Hormuz", time: "8m ago", type: "maritime" },
    { id: 3, severity: "low", text: "Satellite Landsat-9 orbit correction scheduled", time: "15m ago", type: "space" },
    { id: 4, severity: "high", text: "Instability index spike — Eastern Mediterranean", time: "22m ago", type: "instability" },
    { id: 5, severity: "medium", text: "Cargo vessel SHIP-3 entered restricted waters", time: "35m ago", type: "maritime" },
  ];
}

// ── Layer definitions ───────────────────────────────────────────────────────
const LAYERS = {
  flights:    { label: "Live Flights",  icon: "✈️",  color: "#00d4ff" },
  satellites: { label: "Satellites",    icon: "🛰️", color: "#a78bfa" },
  ships:      { label: "Ship Traffic",  icon: "🚢",  color: "#34d399" },
};

// ── Mercator projection helpers ─────────────────────────────────────────────
function latLngToXY(lat, lng, w, h) {
  const x = ((lng + 180) / 360) * w;
  const latRad = (lat * Math.PI) / 180;
  const mercN = Math.log(Math.tan(Math.PI / 4 + latRad / 2));
  const y = h / 2 - (mercN * h) / (2 * Math.PI);
  return { x: Math.max(0, Math.min(w, x)), y: Math.max(0, Math.min(h, y)) };
}

// ── Main GeoApp Component ───────────────────────────────────────────────────
export default function GeoApp() {
  const mapRef = useRef(null);
  const animRef = useRef(null);
  const [mapSize, setMapSize] = useState({ w: 1200, h: 600 });
  const [activeLayers, setActiveLayers] = useState(new Set(["flights"]));
  const [flights, setFlights] = useState([]);
  const [satellites, setSatellites] = useState([]);
  const [ships, setShips] = useState([]);
  const [alerts] = useState(generateAlerts);
  const [sidePanel, setSidePanel] = useState("alerts");
  const [sidePanelOpen, setSidePanelOpen] = useState(true);
  const [hoveredItem, setHoveredItem] = useState(null);
  const [darkShipFilter, setDarkShipFilter] = useState(false);
  const [tick, setTick] = useState(0);

  // Generate initial data
  useEffect(() => {
    setFlights(generateFlights(12));
    setSatellites(generateSatellites(8));
    setShips(generateShips(10));
  }, []);

  // Animate: slowly move entities
  useEffect(() => {
    const id = setInterval(() => {
      setTick((t) => t + 1);
      setFlights((prev) =>
        prev.map((f) => ({
          ...f,
          lat: f.lat + (Math.sin(f.heading * 0.0175) * 0.3),
          lng: f.lng + (Math.cos(f.heading * 0.0175) * 0.4),
          heading: f.heading + (Math.random() - 0.5) * 2,
        }))
      );
      setSatellites((prev) =>
        prev.map((s) => ({
          ...s,
          lng: ((s.lng + 0.8 + 180) % 360) - 180,
          lat: s.lat + Math.sin(Date.now() / 3000 + s.alt) * 0.2,
        }))
      );
      setShips((prev) =>
        prev.map((s) => ({
          ...s,
          lat: s.lat + (Math.sin(s.heading * 0.0175) * 0.05),
          lng: s.lng + (Math.cos(s.heading * 0.0175) * 0.06),
        }))
      );
    }, 2000);
    return () => clearInterval(id);
  }, []);

  // Resize handler
  useEffect(() => {
    const onResize = () => {
      if (mapRef.current) {
        setMapSize({
          w: mapRef.current.offsetWidth,
          h: mapRef.current.offsetHeight,
        });
      }
    };
    onResize();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const toggleLayer = useCallback((key) => {
    setActiveLayers((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  // Filter ships
  const visibleShips = useMemo(() => {
    if (!activeLayers.has("ships")) return [];
    return darkShipFilter ? ships.filter((s) => !s.ais) : ships;
  }, [ships, activeLayers, darkShipFilter]);

  const severityColor = { high: "#ef4444", medium: "#f59e0b", low: "#06b6d4" };

  return (
    <div className="geo-root">
      {/* ── Map Canvas ── */}
      <div className="geo-map" ref={mapRef}>
        {/* SVG grid/world overlay */}
        <svg className="geo-svg" viewBox={`0 0 ${mapSize.w} ${mapSize.h}`} preserveAspectRatio="none">
          {/* Grid lines */}
          {Array.from({ length: 13 }, (_, i) => {
            const y = (i / 12) * mapSize.h;
            return <line key={`h${i}`} x1={0} y1={y} x2={mapSize.w} y2={y} className="geo-gridline" />;
          })}
          {Array.from({ length: 25 }, (_, i) => {
            const x = (i / 24) * mapSize.w;
            return <line key={`v${i}`} x1={x} y1={0} x2={x} y2={mapSize.h} className="geo-gridline" />;
          })}
          {/* Equator */}
          <line x1={0} y1={mapSize.h / 2} x2={mapSize.w} y2={mapSize.h / 2} className="geo-equator" />

          {/* Continent outlines — simplified polygons */}
          <g className="geo-continents">
            {/* Asia */}
            <polygon points={`${mapSize.w*0.55},${mapSize.h*0.15} ${mapSize.w*0.75},${mapSize.h*0.12} ${mapSize.w*0.82},${mapSize.h*0.25} ${mapSize.w*0.78},${mapSize.h*0.42} ${mapSize.w*0.68},${mapSize.h*0.48} ${mapSize.w*0.58},${mapSize.h*0.38} ${mapSize.w*0.52},${mapSize.h*0.28}`} />
            {/* Europe */}
            <polygon points={`${mapSize.w*0.48},${mapSize.h*0.15} ${mapSize.w*0.55},${mapSize.h*0.12} ${mapSize.w*0.55},${mapSize.h*0.28} ${mapSize.w*0.50},${mapSize.h*0.32} ${mapSize.w*0.46},${mapSize.h*0.25}`} />
            {/* Africa */}
            <polygon points={`${mapSize.w*0.46},${mapSize.h*0.35} ${mapSize.w*0.54},${mapSize.h*0.35} ${mapSize.w*0.56},${mapSize.h*0.55} ${mapSize.w*0.52},${mapSize.h*0.72} ${mapSize.w*0.46},${mapSize.h*0.62} ${mapSize.w*0.44},${mapSize.h*0.45}`} />
            {/* North America */}
            <polygon points={`${mapSize.w*0.10},${mapSize.h*0.15} ${mapSize.w*0.28},${mapSize.h*0.12} ${mapSize.w*0.30},${mapSize.h*0.30} ${mapSize.w*0.25},${mapSize.h*0.42} ${mapSize.w*0.15},${mapSize.h*0.38} ${mapSize.w*0.08},${mapSize.h*0.25}`} />
            {/* South America */}
            <polygon points={`${mapSize.w*0.22},${mapSize.h*0.48} ${mapSize.w*0.30},${mapSize.h*0.45} ${mapSize.w*0.32},${mapSize.h*0.60} ${mapSize.w*0.28},${mapSize.h*0.78} ${mapSize.w*0.22},${mapSize.h*0.72} ${mapSize.w*0.20},${mapSize.h*0.55}`} />
            {/* Australia */}
            <polygon points={`${mapSize.w*0.78},${mapSize.h*0.62} ${mapSize.w*0.88},${mapSize.h*0.58} ${mapSize.w*0.90},${mapSize.h*0.68} ${mapSize.w*0.85},${mapSize.h*0.75} ${mapSize.w*0.78},${mapSize.h*0.70}`} />
          </g>

          {/* Flight markers */}
          {activeLayers.has("flights") && flights.map((f) => {
            const { x, y } = latLngToXY(f.lat, f.lng, mapSize.w, mapSize.h);
            return (
              <g key={f.id} className="geo-marker geo-flight"
                onMouseEnter={() => setHoveredItem({ type: "flight", data: f })}
                onMouseLeave={() => setHoveredItem(null)}>
                <circle cx={x} cy={y} r={4} />
                <circle cx={x} cy={y} r={8} className="geo-ping" />
                <text x={x + 8} y={y - 4} className="geo-label">{f.id}</text>
              </g>
            );
          })}

          {/* Satellite markers */}
          {activeLayers.has("satellites") && satellites.map((s) => {
            const { x, y } = latLngToXY(s.lat, s.lng, mapSize.w, mapSize.h);
            return (
              <g key={s.id} className="geo-marker geo-satellite"
                onMouseEnter={() => setHoveredItem({ type: "satellite", data: s })}
                onMouseLeave={() => setHoveredItem(null)}>
                <rect x={x - 3} y={y - 3} width={6} height={6} transform={`rotate(45 ${x} ${y})`} />
                <circle cx={x} cy={y} r={12} className="geo-orbit-ring" />
              </g>
            );
          })}

          {/* Ship markers */}
          {visibleShips.map((s) => {
            const { x, y } = latLngToXY(s.lat, s.lng, mapSize.w, mapSize.h);
            return (
              <g key={s.id} className={`geo-marker geo-ship ${!s.ais ? "dark-ship" : ""}`}
                onMouseEnter={() => setHoveredItem({ type: "ship", data: s })}
                onMouseLeave={() => setHoveredItem(null)}>
                <polygon points={`${x},${y-5} ${x+4},${y+3} ${x-4},${y+3}`} />
                {!s.ais && <circle cx={x} cy={y} r={10} className="geo-dark-ring" />}
              </g>
            );
          })}
        </svg>

        {/* Hover tooltip */}
        {hoveredItem && (
          <div className="geo-tooltip">
            {hoveredItem.type === "flight" && (
              <>
                <strong>{hoveredItem.data.id}</strong> — {hoveredItem.data.from} → {hoveredItem.data.to}
                <br />Alt: {Math.round(hoveredItem.data.alt).toLocaleString()} ft | {Math.round(hoveredItem.data.speed)} kts
              </>
            )}
            {hoveredItem.type === "satellite" && (
              <>
                <strong>{hoveredItem.data.name}</strong>
                <br />Alt: {Math.round(hoveredItem.data.alt).toLocaleString()} km | {hoveredItem.data.type}
              </>
            )}
            {hoveredItem.type === "ship" && (
              <>
                <strong>{hoveredItem.data.name}</strong>
                <br />Speed: {hoveredItem.data.speed.toFixed(1)} kts | AIS: {hoveredItem.data.ais ? "ON" : "OFF ⚠️"}
              </>
            )}
          </div>
        )}

        {/* Stats overlay */}
        <div className="geo-stats">
          <span>✈️ {flights.length}</span>
          <span>🛰️ {satellites.length}</span>
          <span>🚢 {ships.length}</span>
          <span className="geo-stats-time">{new Date().toLocaleTimeString()}</span>
        </div>
      </div>

      {/* ── Layer Controls ── */}
      <div className="geo-layers">
        {Object.entries(LAYERS).map(([key, layer]) => (
          <button
            key={key}
            className={`geo-layer-btn ${activeLayers.has(key) ? "active" : ""}`}
            onClick={() => toggleLayer(key)}
            style={{ "--layer-color": layer.color }}
          >
            <span className="geo-layer-icon">{layer.icon}</span>
            <span className="geo-layer-label">{layer.label}</span>
            <span className={`geo-layer-dot ${activeLayers.has(key) ? "on" : ""}`} />
          </button>
        ))}
        {activeLayers.has("ships") && (
          <button
            className={`geo-layer-btn dark-filter ${darkShipFilter ? "active" : ""}`}
            onClick={() => setDarkShipFilter((d) => !d)}
            style={{ "--layer-color": "#ef4444" }}
          >
            <span className="geo-layer-icon">🔴</span>
            <span className="geo-layer-label">Dark Ships</span>
            <span className={`geo-layer-dot ${darkShipFilter ? "on" : ""}`} />
          </button>
        )}
      </div>

      {/* ── Side Panel ── */}
      <div className={`geo-side ${sidePanelOpen ? "open" : ""}`}>
        <div className="geo-side-tabs">
          <button className={sidePanel === "alerts" ? "active" : ""} onClick={() => { setSidePanel("alerts"); setSidePanelOpen(true); }}>
            Alerts
          </button>
          <button className={sidePanel === "details" ? "active" : ""} onClick={() => { setSidePanel("details"); setSidePanelOpen(true); }}>
            Details
          </button>
          <button className="geo-side-close" onClick={() => setSidePanelOpen(!sidePanelOpen)}>
            {sidePanelOpen ? "◀" : "▶"}
          </button>
        </div>

        {sidePanelOpen && sidePanel === "alerts" && (
          <div className="geo-alerts">
            {alerts.map((a) => (
              <div key={a.id} className={`geo-alert sev-${a.severity}`}>
                <span className="geo-alert-dot" style={{ background: severityColor[a.severity] }} />
                <div className="geo-alert-body">
                  <div className="geo-alert-text">{a.text}</div>
                  <div className="geo-alert-time">{a.time}</div>
                </div>
              </div>
            ))}
          </div>
        )}

        {sidePanelOpen && sidePanel === "details" && (
          <div className="geo-details">
            <div className="geo-detail-section">
              <h4>Active Layers</h4>
              {Array.from(activeLayers).map((key) => (
                <div key={key} className="geo-detail-row">
                  <span>{LAYERS[key]?.icon} {LAYERS[key]?.label}</span>
                  <span className="geo-detail-count">
                    {key === "flights" ? flights.length : key === "satellites" ? satellites.length : visibleShips.length}
                  </span>
                </div>
              ))}
            </div>
            <div className="geo-detail-section">
              <h4>System</h4>
              <div className="geo-detail-row"><span>Data Source</span><span>Simulated</span></div>
              <div className="geo-detail-row"><span>Refresh Rate</span><span>2s</span></div>
              <div className="geo-detail-row"><span>Update #{tick}</span><span>{new Date().toLocaleTimeString()}</span></div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * GeoApp — Geospatial Intelligence Dashboard
 *
 * Full-screen dark map with real-time data layers:
 *   - Live aircraft (OpenSky Network)
 *   - Satellites (CelesTrak)
 *   - Ship tracking with dark-ship anomaly detection
 *   - Instability index heatmap
 *   - Intelligence alerts feed
 *   - AI-generated intel brief
 *   - Panoptic detection overlay
 *   - Traffic density with air quality
 *   - Map tile switching (Default / Satellite / Terrain)
 */

import { useState, useEffect, useCallback, useRef } from "react";
import { MapContainer, TileLayer, Marker, Popup, CircleMarker, Tooltip, useMap } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import "./GeoApp.css";

const BACKEND = (import.meta.env.VITE_WS_BACKEND_URL || "ws://localhost:8000/ws")
    .replace("ws://", "http://")
    .replace("wss://", "https://")
    .replace("/ws", "");

// TomTom Traffic Flow tile overlay
const TOMTOM_KEY = import.meta.env.VITE_TOMTOM_API_KEY || "";
const TOMTOM_TRAFFIC_URL = `https://api.tomtom.com/traffic/map/4/tile/flow/relative0/{z}/{x}/{y}.png?key=${TOMTOM_KEY}&tileSize=256`;

// ── Tile layer definitions ──────────────────────────────────────────────────
const TILE_LAYERS = {
    default: {
        url: "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
        label: "Default",
        icon: "🌑",
        maxZoom: 19,
        attribution: '&copy; <a href="https://carto.com/">CARTO</a>',
    },
    satellite: {
        url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        label: "Satellite",
        icon: "🛰️",
        maxZoom: 18,
        attribution: '&copy; <a href="https://www.esri.com/">Esri</a>',
    },
    terrain: {
        url: "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
        label: "Terrain",
        icon: "⛰️",
        maxZoom: 17,
        attribution: '&copy; <a href="https://opentopomap.org">OpenTopoMap</a>',
    },
};

// ── Custom map icons ────────────────────────────────────────────────────────
const planeIcon = (heading) => L.divIcon({
    html: `<div class="geo-plane-icon" style="transform: rotate(${heading || 0}deg)">✈</div>`,
    className: "geo-icon-wrapper",
    iconSize: [20, 20],
    iconAnchor: [10, 10],
});

const satIcon = L.divIcon({
    html: `<div class="geo-sat-icon">🛰</div>`,
    className: "geo-icon-wrapper",
    iconSize: [16, 16],
    iconAnchor: [8, 8],
});

const shipIcon = (isDark) => L.divIcon({
    html: `<div class="geo-ship-icon ${isDark ? 'dark-ship' : ''}">🚢</div>`,
    className: "geo-icon-wrapper",
    iconSize: [18, 18],
    iconAnchor: [9, 9],
});

const detectionIcon = (icon) => L.divIcon({
    html: `<div class="geo-detection-icon">${icon}</div>`,
    className: "geo-icon-wrapper",
    iconSize: [22, 22],
    iconAnchor: [11, 11],
});

const aqiIcon = (color, aqi) => L.divIcon({
    html: `<div class="geo-aqi-marker" style="background:${color}; box-shadow: 0 0 12px ${color}80">${aqi}</div>`,
    className: "geo-icon-wrapper",
    iconSize: [32, 32],
    iconAnchor: [16, 16],
});

// Vehicle speed icon — color-coded by speed
const vehicleIcon = (v) => {
    const speedColor = v.speed_kmh < 30 ? "#22c55e" : v.speed_kmh < 80 ? "#eab308" : "#ef4444";
    const isOwn = v.is_own;
    return L.divIcon({
        html: `<div class="geo-vehicle-icon ${isOwn ? 'own-vehicle' : ''}" style="border-color:${speedColor}">
            <span class="geo-vehicle-emoji">${v.icon}</span>
            <span class="geo-speed-badge" style="background:${speedColor}">${Math.round(v.speed_kmh)}</span>
        </div>`,
        className: "geo-icon-wrapper",
        iconSize: [36, 36],
        iconAnchor: [18, 18],
    });
};

// ── Layer definitions ───────────────────────────────────────────────────────
const LAYERS = {
    flights: { label: "Live Flights", icon: "✈️", color: "#00d4ff", source: "live" },
    satellites: { label: "Satellites", icon: "🛰️", color: "#a78bfa", source: "live" },
    ships: { label: "Ship Traffic", icon: "🚢", color: "#34d399", source: "sim" },
    instability: { label: "Instability Index", icon: "🔥", color: "#ef4444", source: "sim" },
    detections: { label: "Detections", icon: "🎯", color: "#f59e0b", source: "sim" },
    traffic: { label: "Traffic Density", icon: "🚦", color: "#f97316", source: "live" },
    vehicleSpeeds: { label: "Vehicle Speeds", icon: "🚗", color: "#06b6d4", source: "sim" },
};

// Stat bar items mapped to layers
const STAT_LAYER_MAP = {
    flights: "flights",
    satellites: "satellites",
    ships: "ships",
    darkShips: "ships",
};


// ── Map view updater component ──────────────────────────────────────────────
function MapViewUpdater({ center, zoom }) {
    const map = useMap();
    useEffect(() => {
        if (center) map.setView(center, zoom);
    }, [center, zoom, map]);
    return null;
}


// ── Main GeoApp Component ───────────────────────────────────────────────────
export default function GeoApp() {
    const [activeLayers, setActiveLayers] = useState(new Set(["flights"]));
    const [flights, setFlights] = useState([]);
    const [satellites, setSatellites] = useState([]);
    const [ships, setShips] = useState([]);
    const [instability, setInstability] = useState([]);
    const [detections, setDetections] = useState([]);
    const [airQuality, setAirQuality] = useState([]);
    const [vehicleSpeeds, setVehicleSpeeds] = useState([]);
    const [showAirQuality, setShowAirQuality] = useState(true);
    const [alerts, setAlerts] = useState([]);
    const [intelBrief, setIntelBrief] = useState(null);
    const [briefLoading, setBriefLoading] = useState(false);
    const [sidePanel, setSidePanel] = useState("alerts"); // alerts | brief
    const [sidePanelOpen, setSidePanelOpen] = useState(true);
    const [darkShipFilter, setDarkShipFilter] = useState(false);
    const [mapStyle, setMapStyle] = useState("default");
    const [stats, setStats] = useState({ flights: 0, satellites: 0, ships: 0, darkShips: 0 });
    const refreshTimerRef = useRef(null);

    const toggleLayer = (layer) => {
        setActiveLayers((prev) => {
            const next = new Set(prev);
            if (next.has(layer)) next.delete(layer);
            else next.add(layer);
            return next;
        });
    };

    // ── Stat bar click handler ────────────────────────────────────────────
    const handleStatClick = (statKey) => {
        const layerKey = STAT_LAYER_MAP[statKey];
        if (!layerKey) return;

        if (statKey === "darkShips") {
            // Toggle dark ship filter; ensure ships layer is active
            if (!activeLayers.has("ships")) {
                setActiveLayers((prev) => new Set([...prev, "ships"]));
            }
            setDarkShipFilter((prev) => !prev);
        } else {
            toggleLayer(layerKey);
            if (statKey !== "ships") setDarkShipFilter(false);
        }
    };

    // ── Data fetchers ────────────────────────────────────────────────────
    const fetchFlights = useCallback(async () => {
        try {
            const resp = await fetch(`${BACKEND}/api/geo/flights?limit=500`);
            const data = await resp.json();
            setFlights(data.flights || []);
            setStats((s) => ({ ...s, flights: data.count || 0 }));
        } catch (e) { console.warn("Flights fetch error:", e); }
    }, []);

    const fetchSatellites = useCallback(async () => {
        try {
            const resp = await fetch(`${BACKEND}/api/geo/satellites?limit=200`);
            const data = await resp.json();
            setSatellites(data.satellites || []);
            setStats((s) => ({ ...s, satellites: data.count || 0 }));
        } catch (e) { console.warn("Satellites fetch error:", e); }
    }, []);

    const fetchShips = useCallback(async () => {
        try {
            const resp = await fetch(`${BACKEND}/api/geo/ships?limit=300`);
            const data = await resp.json();
            setShips(data.ships || []);
            setStats((s) => ({ ...s, ships: data.count || 0, darkShips: data.dark_ships || 0 }));
        } catch (e) { console.warn("Ships fetch error:", e); }
    }, []);

    const fetchInstability = useCallback(async () => {
        try {
            const resp = await fetch(`${BACKEND}/api/geo/instability`);
            const data = await resp.json();
            setInstability(data.regions || []);
        } catch (e) { console.warn("Instability fetch error:", e); }
    }, []);

    const fetchDetections = useCallback(async () => {
        try {
            const resp = await fetch(`${BACKEND}/api/geo/detections?limit=50`);
            const data = await resp.json();
            setDetections(data.detections || []);
        } catch (e) { console.warn("Detections fetch error:", e); }
    }, []);

    const fetchAirQuality = useCallback(async () => {
        try {
            const resp = await fetch(`${BACKEND}/api/geo/air-quality`);
            const data = await resp.json();
            setAirQuality(data.stations || []);
        } catch (e) { console.warn("Air quality fetch error:", e); }
    }, []);

    const fetchVehicleSpeeds = useCallback(async () => {
        try {
            const resp = await fetch(`${BACKEND}/api/geo/vehicle-speeds?radius_km=10`);
            const data = await resp.json();
            setVehicleSpeeds(data.vehicles || []);
        } catch (e) { console.warn("Vehicle speeds fetch error:", e); }
    }, []);

    const fetchAlerts = useCallback(async () => {
        try {
            const resp = await fetch(`${BACKEND}/api/geo/alerts?limit=20`);
            const data = await resp.json();
            setAlerts(data.alerts || []);
        } catch (e) { console.warn("Alerts fetch error:", e); }
    }, []);

    const generateBrief = useCallback(async (region = "global", focus = "security") => {
        setBriefLoading(true);
        try {
            const resp = await fetch(`${BACKEND}/api/geo/brief`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ region, focus }),
            });
            const data = await resp.json();
            setIntelBrief(data);
        } catch (e) { console.warn("Brief generation error:", e); }
        setBriefLoading(false);
    }, []);

    // ── Initial load + periodic refresh ──────────────────────────────────
    useEffect(() => {
        fetchFlights();
        fetchAlerts();
        fetchInstability();
        fetchAirQuality();

        const timer = setInterval(() => {
            if (activeLayers.has("flights")) fetchFlights();
            if (activeLayers.has("ships")) fetchShips();
            if (activeLayers.has("vehicleSpeeds")) fetchVehicleSpeeds();
        }, 15000);
        refreshTimerRef.current = timer;

        return () => clearInterval(timer);
    }, []);

    // Load layer data when toggled on
    useEffect(() => {
        if (activeLayers.has("flights") && flights.length === 0) fetchFlights();
        if (activeLayers.has("satellites") && satellites.length === 0) fetchSatellites();
        if (activeLayers.has("ships") && ships.length === 0) fetchShips();
        if (activeLayers.has("instability") && instability.length === 0) fetchInstability();
        if (activeLayers.has("detections") && detections.length === 0) fetchDetections();
        if (activeLayers.has("vehicleSpeeds") && vehicleSpeeds.length === 0) fetchVehicleSpeeds();
    }, [activeLayers]);

    // ── Helpers ──────────────────────────────────────────────────────────
    const severityColor = (level) => {
        switch (level) {
            case "critical": return "#ef4444";
            case "high": return "#f97316";
            case "elevated": return "#eab308";
            case "medium": return "#eab308";
            case "moderate": return "#3b82f6";
            case "low": return "#22c55e";
            default: return "#6b7280";
        }
    };

    const instabilityRadius = (score) => Math.max(8, score / 3);

    // Filter ships for dark ship mode
    const displayedShips = darkShipFilter
        ? ships.filter((s) => s.is_dark)
        : ships;

    const currentTile = TILE_LAYERS[mapStyle];

    return (
        <div className="geo-root">
            {/* ── Map Style Switcher (top right) ── */}
            <div className="geo-tile-switcher">
                {Object.entries(TILE_LAYERS).map(([key, tile]) => (
                    <button
                        key={key}
                        className={`geo-tile-btn ${mapStyle === key ? "active" : ""}`}
                        onClick={() => setMapStyle(key)}
                        title={tile.label}
                    >
                        <span className="geo-tile-icon">{tile.icon}</span>
                        <span className="geo-tile-label">{tile.label}</span>
                    </button>
                ))}
            </div>

            {/* ── Layer Controls ── */}
            <div className="geo-layer-panel">
                <div className="geo-layer-title">
                    <span className="geo-radar-icon">◎</span>
                    LAYERS
                </div>
                {Object.entries(LAYERS).map(([key, info]) => (
                    <button
                        key={key}
                        className={`geo-layer-btn ${activeLayers.has(key) ? "active" : ""}`}
                        onClick={() => toggleLayer(key)}
                        style={{
                            "--layer-color": info.color,
                        }}
                    >
                        <span className="geo-layer-icon">{info.icon}</span>
                        <span className="geo-layer-label">{info.label}</span>
                        <span className={`geo-source-badge ${info.source}`}>
                            {info.source === "live" ? "LIVE" : "SIM"}
                        </span>
                        <span className={`geo-layer-dot ${activeLayers.has(key) ? "on" : ""}`} />
                    </button>
                ))}

                {/* Air Quality sub-toggle (visible when traffic is active) */}
                {activeLayers.has("traffic") && (
                    <div className="geo-sub-toggle">
                        <button
                            className={`geo-layer-btn sub ${showAirQuality ? "active" : ""}`}
                            onClick={() => setShowAirQuality((p) => !p)}
                            style={{ "--layer-color": "#10b981" }}
                        >
                            <span className="geo-layer-icon">🌬️</span>
                            <span className="geo-layer-label">Air Quality</span>
                            <span className={`geo-layer-dot ${showAirQuality ? "on" : ""}`} />
                        </button>
                    </div>
                )}
            </div>

            {/* ── Stats Bar (clickable) ── */}
            <div className="geo-stats-bar">
                <button
                    className={`geo-stat clickable ${activeLayers.has("flights") ? "stat-active" : ""}`}
                    onClick={() => handleStatClick("flights")}
                    title="Toggle Aircraft layer"
                >
                    <span className="geo-stat-icon">✈️</span>
                    <span className="geo-stat-value">{stats.flights}</span>
                    <span className="geo-stat-label">Aircraft</span>
                </button>
                <button
                    className={`geo-stat clickable ${activeLayers.has("satellites") ? "stat-active" : ""}`}
                    onClick={() => handleStatClick("satellites")}
                    title="Toggle Satellites layer"
                >
                    <span className="geo-stat-icon">🛰️</span>
                    <span className="geo-stat-value">{stats.satellites}</span>
                    <span className="geo-stat-label">Satellites</span>
                </button>
                <button
                    className={`geo-stat clickable ${activeLayers.has("ships") && !darkShipFilter ? "stat-active" : ""}`}
                    onClick={() => handleStatClick("ships")}
                    title="Toggle Vessels layer"
                >
                    <span className="geo-stat-icon">🚢</span>
                    <span className="geo-stat-value">{stats.ships}</span>
                    <span className="geo-stat-label">Vessels</span>
                </button>
                <button
                    className={`geo-stat alert clickable ${darkShipFilter ? "stat-active" : ""}`}
                    onClick={() => handleStatClick("darkShips")}
                    title="Toggle Dark Ships filter"
                >
                    <span className="geo-stat-icon">⚠️</span>
                    <span className="geo-stat-value">{stats.darkShips}</span>
                    <span className="geo-stat-label">Dark Ships</span>
                </button>
            </div>

            {/* ── Map ── */}
            <div className="geo-map-container">
                <MapContainer
                    center={[20, 0]}
                    zoom={3}
                    style={{ height: "100%", width: "100%" }}
                    zoomControl={false}
                    attributionControl={false}
                >
                    <TileLayer
                        key={mapStyle}
                        url={currentTile.url}
                        maxZoom={currentTile.maxZoom}
                    />

                    {/* Flights layer */}
                    {activeLayers.has("flights") && flights.map((f, i) => (
                        <Marker key={`f-${i}`} position={[f.lat, f.lon]} icon={planeIcon(f.heading)}>
                            <Popup className="geo-popup">
                                <div className="geo-popup-title">✈ {f.callsign || "Unknown"}</div>
                                <div>Country: {f.country}</div>
                                <div>Altitude: {Math.round(f.alt_m)}m</div>
                                <div>Speed: {Math.round(f.velocity_ms * 3.6)} km/h</div>
                                <div>ICAO: {f.icao24}</div>
                            </Popup>
                        </Marker>
                    ))}

                    {/* Satellites layer */}
                    {activeLayers.has("satellites") && satellites.map((s, i) => (
                        <Marker key={`s-${i}`} position={[s.lat, s.lon]} icon={satIcon}>
                            <Popup className="geo-popup">
                                <div className="geo-popup-title">🛰 {s.name}</div>
                                <div>Altitude: {s.alt_km} km</div>
                                <div>Velocity: {s.velocity_kms} km/s</div>
                            </Popup>
                        </Marker>
                    ))}

                    {/* Ships layer (with optional dark-ship filter) */}
                    {activeLayers.has("ships") && displayedShips.map((s, i) => (
                        <Marker key={`sh-${i}`} position={[s.lat, s.lon]} icon={shipIcon(s.is_dark)}>
                            <Popup className="geo-popup">
                                <div className={`geo-popup-title ${s.is_dark ? "dark-alert" : ""}`}>
                                    {s.is_dark ? "⚠ " : ""}🚢 {s.name}
                                </div>
                                <div>Type: {s.type} | Flag: {s.flag}</div>
                                <div>Speed: {s.speed_knots} kn | Heading: {s.heading}°</div>
                                {s.is_dark && (
                                    <div className="geo-dark-alert">
                                        <div>Anomaly Score: {(s.anomaly_score * 100).toFixed(0)}%</div>
                                        {s.anomaly_reasons.map((r, j) => (
                                            <div key={j} className="geo-anomaly-reason">• {r}</div>
                                        ))}
                                    </div>
                                )}
                            </Popup>
                        </Marker>
                    ))}

                    {/* Instability layer */}
                    {activeLayers.has("instability") && instability.map((r, i) => (
                        <CircleMarker
                            key={`ins-${i}`}
                            center={[r.lat, r.lon]}
                            radius={instabilityRadius(r.score)}
                            pathOptions={{
                                color: severityColor(r.level),
                                fillColor: severityColor(r.level),
                                fillOpacity: 0.35,
                                weight: 2,
                            }}
                        >
                            <Tooltip permanent className="geo-instability-tooltip">
                                {r.name}: {r.score}
                            </Tooltip>
                        </CircleMarker>
                    ))}

                    {/* Detections layer */}
                    {activeLayers.has("detections") && detections.map((d, i) => (
                        <Marker key={`det-${i}`} position={[d.lat, d.lon]} icon={detectionIcon(d.icon)}>
                            <Popup className="geo-popup">
                                <div className="geo-popup-title">{d.icon} {d.type.replace(/_/g, " ")}</div>
                                <div>Confidence: {(d.confidence * 100).toFixed(0)}%</div>
                                <div>Source: {d.source}</div>
                                <div>Severity: <span style={{ color: severityColor(d.severity) }}>{d.severity}</span></div>
                            </Popup>
                        </Marker>
                    ))}

                    {/* Traffic density layer — TomTom real-time flow tiles */}
                    {activeLayers.has("traffic") && (
                        <TileLayer
                            url={TOMTOM_TRAFFIC_URL}
                            maxZoom={18}
                            opacity={0.7}
                            zIndex={10}
                        />
                    )}

                    {/* Air Quality markers (shown when traffic active + AQI toggle on) */}
                    {activeLayers.has("traffic") && showAirQuality && airQuality.map((aq, i) => (
                        <Marker key={`aq-${i}`} position={[aq.lat, aq.lon]} icon={aqiIcon(aq.color, aq.aqi)}>
                            <Popup className="geo-popup">
                                <div className="geo-popup-title" style={{ color: aq.color }}>
                                    🌬️ {aq.name}
                                </div>
                                <div>AQI: <strong style={{ color: aq.color }}>{aq.aqi}</strong> — {aq.category}</div>
                                <div>Dominant Pollutant: {aq.dominant?.toUpperCase()}</div>
                                <div className="geo-aqi-bar">
                                    <div className="geo-aqi-fill" style={{
                                        width: `${Math.min(100, aq.aqi / 3)}%`,
                                        background: aq.color,
                                    }} />
                                </div>
                            </Popup>
                        </Marker>
                    ))}

                    {/* Vehicle Speed markers — cell tower tracked */}
                    {activeLayers.has("vehicleSpeeds") && vehicleSpeeds.map((v) => (
                        <Marker key={`veh-${v.id}`} position={[v.lat, v.lon]} icon={vehicleIcon(v)}>
                            <Popup className="geo-popup">
                                <div className="geo-popup-title">
                                    {v.icon} {v.is_own ? "Your Vehicle" : `${v.type.charAt(0).toUpperCase() + v.type.slice(1)}`}
                                </div>
                                <div>Speed: <strong style={{ color: v.speed_kmh < 30 ? "#22c55e" : v.speed_kmh < 80 ? "#eab308" : "#ef4444" }}>
                                    {v.speed_kmh} km/h
                                </strong> ({v.speed_label})</div>
                                <div>Heading: {v.heading}°</div>
                                <div>Cell Tower: <code>{v.cell_tower_id}</code></div>
                                <div>Signal: {v.signal_strength}%</div>
                                <div style={{ fontSize: "0.7rem", opacity: 0.6, marginTop: 4 }}>
                                    📡 Tracked via cell tower triangulation
                                </div>
                            </Popup>
                        </Marker>
                    ))}
                </MapContainer>
            </div>

            {/* ── Air Quality Legend (shown when traffic + AQI active) ── */}
            {activeLayers.has("traffic") && showAirQuality && (
                <div className="geo-aqi-legend">
                    <div className="geo-aqi-legend-title">Air Quality Index</div>
                    <div className="geo-aqi-legend-items">
                        <span className="geo-aqi-legend-item" style={{ color: "#22c55e" }}>● Good</span>
                        <span className="geo-aqi-legend-item" style={{ color: "#eab308" }}>● Moderate</span>
                        <span className="geo-aqi-legend-item" style={{ color: "#f97316" }}>● Sensitive</span>
                        <span className="geo-aqi-legend-item" style={{ color: "#ef4444" }}>● Unhealthy</span>
                        <span className="geo-aqi-legend-item" style={{ color: "#a855f7" }}>● Very Unhealthy</span>
                        <span className="geo-aqi-legend-item" style={{ color: "#7f1d1d" }}>● Hazardous</span>
                    </div>
                </div>
            )}

            {/* ── Side Panel (minimizable) ── */}
            <div className={`geo-side-panel ${!sidePanelOpen ? "minimized" : ""}`}>
                <button
                    className="geo-panel-toggle"
                    onClick={() => setSidePanelOpen((p) => !p)}
                    title={sidePanelOpen ? "Minimize panel" : "Expand panel"}
                >
                    {sidePanelOpen ? "▶" : "◀"}
                </button>

                {sidePanelOpen ? (
                    <>
                        <div className="geo-side-tabs">
                            <button
                                className={`geo-side-tab ${sidePanel === "alerts" ? "active" : ""}`}
                                onClick={() => { setSidePanel("alerts"); if (alerts.length === 0) fetchAlerts(); }}
                            >
                                🔔 Alerts
                            </button>
                            <button
                                className={`geo-side-tab ${sidePanel === "brief" ? "active" : ""}`}
                                onClick={() => { setSidePanel("brief"); if (!intelBrief) generateBrief(); }}
                            >
                                📋 Intel Brief
                            </button>
                        </div>

                        <div className="geo-side-content">
                            {sidePanel === "alerts" && (
                                <div className="geo-alerts-list">
                                    {alerts.length === 0 && (
                                        <div className="geo-loading">Loading alerts...</div>
                                    )}
                                    {alerts.map((a, i) => (
                                        <div key={i} className={`geo-alert-item severity-${a.severity}`}>
                                            <div className="geo-alert-severity" style={{ background: severityColor(a.severity) }}>
                                                {a.severity?.toUpperCase()}
                                            </div>
                                            <div className="geo-alert-title">{a.title}</div>
                                            <div className="geo-alert-meta">
                                                {a.source} • {a.datetime?.slice(0, 10)}
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}

                            {sidePanel === "brief" && (
                                <div className="geo-brief-panel">
                                    <div className="geo-brief-actions">
                                        <button className="geo-brief-btn" onClick={() => generateBrief("global", "security")} disabled={briefLoading}>
                                            {briefLoading ? "Generating..." : "🔄 Refresh Brief"}
                                        </button>
                                        <select className="geo-brief-select" onChange={(e) => generateBrief(e.target.value)}>
                                            <option value="global">🌍 Global</option>
                                            <option value="Middle East">Middle East</option>
                                            <option value="Europe">Europe</option>
                                            <option value="Asia-Pacific">Asia-Pacific</option>
                                            <option value="Africa">Africa</option>
                                            <option value="South Asia">South Asia</option>
                                        </select>
                                    </div>
                                    {intelBrief ? (
                                        <div className="geo-brief-content">
                                            <div className="geo-brief-timestamp">
                                                Generated: {intelBrief.generated_at?.slice(0, 19).replace("T", " ")} UTC
                                            </div>
                                            <div className="geo-brief-text">{intelBrief.brief}</div>
                                        </div>
                                    ) : (
                                        <div className="geo-loading">
                                            {briefLoading ? "🧠 AI analyzing global situation..." : "Click Refresh to generate an intelligence brief."}
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>
                    </>
                ) : (
                    /* Minimized: show vertical icon strip */
                    <div className="geo-side-minimized-icons">
                        <button
                            className={`geo-mini-icon ${sidePanel === "alerts" ? "active" : ""}`}
                            onClick={() => { setSidePanel("alerts"); setSidePanelOpen(true); }}
                            title="Alerts"
                        >
                            🔔
                        </button>
                        <button
                            className={`geo-mini-icon ${sidePanel === "brief" ? "active" : ""}`}
                            onClick={() => { setSidePanel("brief"); setSidePanelOpen(true); if (!intelBrief) generateBrief(); }}
                            title="Intel Brief"
                        >
                            📋
                        </button>
                    </div>
                )}
            </div>
        </div>
    );
}

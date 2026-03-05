/**
 * NearestStores — Location-based store finder with mini-map.
 *
 * Features:
 *   - Browser Geolocation API for user coords
 *   - OpenStreetMap Overpass API for nearby POIs (free, no key)
 *   - Category filter (all, restaurants, pharmacies, groceries, cafes)
 *   - Card-style list with name, distance, category, open status
 *   - "Get Directions" button → Google Maps
 *   - Embedded Leaflet.js mini-map with markers
 *   - Auto-refresh every 5 minutes
 */

import { useState, useEffect, useCallback, useRef } from "react";

// ── Category definitions ────────────────────────────────────────────────
const CATEGORIES = [
    { key: "all", label: "All", icon: "📍" },
    { key: "restaurant", label: "Restaurants", icon: "🍽️" },
    { key: "pharmacy", label: "Pharmacies", icon: "💊" },
    { key: "supermarket", label: "Grocery", icon: "🛒" },
    { key: "cafe", label: "Cafes", icon: "☕" },
];

// Overpass QL query for nearby amenities
function buildOverpassQuery(lat, lon, radius = 1500, category = "all") {
    const categoryFilter = category === "all"
        ? `["amenity"~"restaurant|pharmacy|cafe|fast_food|clinic"]["name"]`
        : category === "supermarket"
            ? `["shop"="supermarket"]["name"]`
            : `["amenity"="${category}"]["name"]`;

    return `
    [out:json][timeout:10];
    (
      node${categoryFilter}(around:${radius},${lat},${lon});
    );
    out body 15;
  `;
}

// Calculate distance between two coordinates (Haversine)
function calcDistance(lat1, lon1, lat2, lon2) {
    const R = 6371; // km
    const dLat = ((lat2 - lat1) * Math.PI) / 180;
    const dLon = ((lon2 - lon1) * Math.PI) / 180;
    const a =
        Math.sin(dLat / 2) ** 2 +
        Math.cos((lat1 * Math.PI) / 180) *
        Math.cos((lat2 * Math.PI) / 180) *
        Math.sin(dLon / 2) ** 2;
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    return R * c;
}

function formatDistance(km) {
    if (km < 1) return `${Math.round(km * 1000)}m`;
    return `${km.toFixed(1)}km`;
}

// Map amenity/shop type to a user-friendly label
function getStoreType(tags) {
    if (tags.shop === "supermarket") return "Grocery";
    const map = {
        restaurant: "Restaurant",
        pharmacy: "Pharmacy",
        cafe: "Cafe",
        fast_food: "Fast Food",
        clinic: "Clinic",
    };
    return map[tags.amenity] || tags.amenity || "Store";
}

export function NearestStores() {
    const [location, setLocation] = useState(null);
    const [stores, setStores] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [category, setCategory] = useState("all");
    const [permissionDenied, setPermissionDenied] = useState(false);
    const mapContainerRef = useRef(null);
    const mapRef = useRef(null);
    const markersRef = useRef([]);
    const refreshTimerRef = useRef(null);

    // ── Get user location ───────────────────────────────────────────────
    const getLocation = useCallback(() => {
        if (!navigator.geolocation) {
            setError("Geolocation not supported");
            return;
        }
        setLoading(true);
        setError(null);
        navigator.geolocation.getCurrentPosition(
            (pos) => {
                setLocation({ lat: pos.coords.latitude, lon: pos.coords.longitude });
                setPermissionDenied(false);
                setLoading(false);
            },
            (err) => {
                if (err.code === 1) {
                    setPermissionDenied(true);
                    setError("Location permission denied");
                } else {
                    setError("Could not get location");
                }
                setLoading(false);
            },
            { enableHighAccuracy: true, timeout: 10000 }
        );
    }, []);

    // ── Fetch nearby stores from Overpass API ───────────────────────────
    const fetchStores = useCallback(async () => {
        if (!location) return;
        setLoading(true);
        setError(null);

        try {
            const query = buildOverpassQuery(location.lat, location.lon, 1500, category);
            const resp = await fetch("https://overpass-api.de/api/interpreter", {
                method: "POST",
                body: `data=${encodeURIComponent(query)}`,
                headers: { "Content-Type": "application/x-www-form-urlencoded" },
            });

            if (!resp.ok) throw new Error("Overpass API error");

            const data = await resp.json();
            const results = (data.elements || [])
                .map((el) => ({
                    id: el.id,
                    name: el.tags?.name || "Unnamed",
                    lat: el.lat,
                    lon: el.lon,
                    type: getStoreType(el.tags || {}),
                    distance: calcDistance(location.lat, location.lon, el.lat, el.lon),
                    phone: el.tags?.phone || el.tags?.["contact:phone"] || null,
                    openingHours: el.tags?.opening_hours || null,
                    cuisine: el.tags?.cuisine || null,
                }))
                .sort((a, b) => a.distance - b.distance)
                .slice(0, 12);

            setStores(results);
        } catch (err) {
            console.warn("[NearestStores] Fetch error:", err);
            setError("Could not load nearby stores");
        } finally {
            setLoading(false);
        }
    }, [location, category]);

    // ── Request location on mount ───────────────────────────────────────
    useEffect(() => {
        getLocation();
    }, [getLocation]);

    // ── Fetch stores when location or category changes ──────────────────
    useEffect(() => {
        if (location) {
            fetchStores();
        }
    }, [location, category, fetchStores]);

    // ── Auto-refresh every 5 minutes ────────────────────────────────────
    useEffect(() => {
        if (!location) return;
        refreshTimerRef.current = setInterval(fetchStores, 5 * 60 * 1000);
        return () => clearInterval(refreshTimerRef.current);
    }, [location, fetchStores]);

    // ── Initialize Leaflet map ──────────────────────────────────────────
    useEffect(() => {
        if (!location || !mapContainerRef.current || !window.L) return;

        // Create map if not exists
        if (!mapRef.current) {
            mapRef.current = window.L.map(mapContainerRef.current, {
                zoomControl: false,
                attributionControl: false,
            }).setView([location.lat, location.lon], 14);

            window.L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
                maxZoom: 19,
            }).addTo(mapRef.current);

            // User marker
            window.L.circleMarker([location.lat, location.lon], {
                radius: 8,
                fillColor: "#00d4ff",
                color: "#0891b2",
                weight: 2,
                fillOpacity: 0.8,
            })
                .addTo(mapRef.current)
                .bindPopup("You are here");
        } else {
            mapRef.current.setView([location.lat, location.lon], 14);
        }

        // Clear old markers
        markersRef.current.forEach((m) => mapRef.current.removeLayer(m));
        markersRef.current = [];

        // Add store markers
        stores.forEach((store) => {
            const marker = window.L.circleMarker([store.lat, store.lon], {
                radius: 6,
                fillColor: "#f5a623",
                color: "#d97706",
                weight: 1.5,
                fillOpacity: 0.8,
            })
                .addTo(mapRef.current)
                .bindPopup(`<strong>${store.name}</strong><br>${store.type} · ${formatDistance(store.distance)}`);
            markersRef.current.push(marker);
        });

        // Fit bounds if stores exist
        if (stores.length > 0) {
            const allCoords = [
                [location.lat, location.lon],
                ...stores.map((s) => [s.lat, s.lon]),
            ];
            mapRef.current.fitBounds(allCoords, { padding: [20, 20], maxZoom: 15 });
        }
    }, [location, stores]);

    // Cleanup map on unmount
    useEffect(() => {
        return () => {
            if (mapRef.current) {
                mapRef.current.remove();
                mapRef.current = null;
            }
        };
    }, []);

    // ── "Get Directions" handler ────────────────────────────────────────
    const openDirections = (store) => {
        const url = `https://www.google.com/maps/dir/?api=1&destination=${store.lat},${store.lon}&travelmode=walking`;
        window.open(url, "_blank");
    };

    // ── Render ──────────────────────────────────────────────────────────
    if (permissionDenied || (!location && !loading)) {
        return (
            <div className="nearest-stores">
                <div className="ns-permission-prompt">
                    <span className="ns-permission-icon">📍</span>
                    <p>Enable location to find nearby stores</p>
                    <button className="ns-enable-btn hoverable" onClick={getLocation}>
                        Enable Location
                    </button>
                </div>
            </div>
        );
    }

    return (
        <div className="nearest-stores" id="nearest-stores">
            {/* Category filter */}
            <div className="ns-categories">
                {CATEGORIES.map((cat) => (
                    <button
                        key={cat.key}
                        className={`ns-cat-btn hoverable ${category === cat.key ? "active" : ""}`}
                        onClick={() => setCategory(cat.key)}
                    >
                        <span>{cat.icon}</span>
                        <span>{cat.label}</span>
                    </button>
                ))}
            </div>

            {/* Mini-map */}
            <div className="ns-map-wrapper">
                <div ref={mapContainerRef} className="ns-map" id="nearest-stores-map" />
                {loading && <div className="ns-map-loading">Loading...</div>}
            </div>

            {/* Error state */}
            {error && !loading && (
                <div className="ns-error">
                    <span>⚠ {error}</span>
                    <button className="ns-retry-btn hoverable" onClick={fetchStores}>Retry</button>
                </div>
            )}

            {/* Store list */}
            <div className="ns-store-list">
                {stores.length === 0 && !loading && !error && (
                    <p className="ns-empty">No stores found nearby</p>
                )}
                {stores.slice(0, 6).map((store) => (
                    <div className="ns-store-card" key={store.id}>
                        <div className="ns-store-info">
                            <span className="ns-store-name">{store.name}</span>
                            <span className="ns-store-meta">
                                {store.type} · {formatDistance(store.distance)}
                                {store.cuisine && ` · ${store.cuisine}`}
                            </span>
                            {store.openingHours && (
                                <span className="ns-store-hours">{store.openingHours}</span>
                            )}
                        </div>
                        <button
                            className="ns-directions-btn hoverable"
                            onClick={() => openDirections(store)}
                            title="Get Directions"
                        >
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                <path d="M3 12h18M13 5l7 7-7 7" />
                            </svg>
                        </button>
                    </div>
                ))}
            </div>

            {/* Refresh button */}
            {location && (
                <button className="ns-refresh-btn hoverable" onClick={fetchStores} disabled={loading}>
                    {loading ? "⏳ Loading..." : "🔄 Refresh"}
                </button>
            )}
        </div>
    );
}

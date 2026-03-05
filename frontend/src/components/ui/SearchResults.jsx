/**
 * SearchResults — Right panel showing "Searched By Command" results.
 * Fetches live YouTube videos based on conversation topic.
 * Shows dynamic search result data from parent.
 * Includes NearestStores component for location-based store finder.
 */

import { useState, useEffect, useRef, useCallback } from "react";
import { NearestStores } from "./NearestStores";

const BACKEND = (import.meta.env.VITE_WS_BACKEND_URL || "ws://localhost:8000/ws")
    .replace("ws://", "http://")
    .replace("wss://", "https://")
    .replace("/ws", "");

export function SearchResults({ result }) {
    const title = result?.title || "Hover Board";
    const category = result?.category || "Personal Transporter";
    const confidence = result?.confidence || "92.8";

    const [videos, setVideos] = useState([]);
    const [videoLoading, setVideoLoading] = useState(false);
    const lastQueryRef = useRef("");
    const debounceRef = useRef(null);

    // Fetch YouTube videos when topic changes (debounced 3s)
    const fetchVideos = useCallback(async (query) => {
        if (!query || query === lastQueryRef.current) return;
        lastQueryRef.current = query;
        setVideoLoading(true);

        try {
            const resp = await fetch(
                `${BACKEND}/api/youtube-search?q=${encodeURIComponent(query)}&max=4`
            );
            if (resp.ok) {
                const data = await resp.json();
                if (data.results && data.results.length > 0) {
                    setVideos(data.results);
                }
            }
        } catch (err) {
            console.warn("[Videos] Fetch failed:", err);
        } finally {
            setVideoLoading(false);
        }
    }, []);

    // Debounce topic changes (3s for meaningful shifts)
    useEffect(() => {
        if (!result?.query) return;

        clearTimeout(debounceRef.current);
        debounceRef.current = setTimeout(() => {
            fetchVideos(result.query);
        }, 3000);

        return () => clearTimeout(debounceRef.current);
    }, [result?.query, fetchVideos]);

    return (
        <aside className="search-results-panel" id="search-results">
            <h2 className="panel-title">Searched By Command</h2>

            {/* Meta */}
            <div className="sr-meta">
                <div className="sr-meta-row">
                    <span className="sr-meta-label">Title</span>
                    <span className="sr-meta-value">{title}</span>
                </div>
                <div className="sr-meta-row">
                    <span className="sr-meta-label">Category</span>
                    <span className="sr-meta-value">{category}</span>
                </div>
                <div className="sr-meta-row sr-meta-row-results">
                    <div>
                        <span className="sr-meta-label">Search Results</span>
                        <span className="sr-meta-pct">{confidence}%</span>
                    </div>
                    <div className="sr-meta-links">
                        <a href="#" className="sr-link" id="link-view-all">View All</a>
                        <a href="#" className="sr-link" id="link-top-results">View Top Results</a>
                    </div>
                </div>
            </div>

            {/* Live query indicator */}
            {result && (
                <div className="sr-live-badge">
                    <span className="sr-live-dot" />
                    <span>Live Result</span>
                </div>
            )}

            {/* Videos — Live YouTube */}
            <div className="sr-section">
                <h3 className="sr-section-title">
                    Videos
                    {videoLoading && <span className="sr-loading-indicator"> ⏳</span>}
                </h3>
                <div className="sr-videos">
                    {videos.length > 0 ? (
                        videos.map((v, i) => (
                            <a
                                className="sr-video-card"
                                key={i}
                                id={`video-card-${i}`}
                                href={v.url}
                                target="_blank"
                                rel="noopener noreferrer"
                                style={{ textDecoration: "none", color: "inherit" }}
                            >
                                {v.thumbnail && (
                                    <img src={v.thumbnail} alt={v.title} className="sr-video-thumb" />
                                )}
                                <div className="sr-video-info">
                                    <span className="sr-video-title">{v.title}</span>
                                    <span className="sr-video-source">
                                        {v.channel || "YouTube"} · {v.duration}
                                    </span>
                                    {v.view_count && (
                                        <span className="sr-video-views">{v.view_count}</span>
                                    )}
                                </div>
                                <div className="sr-video-play" aria-label={`Play ${v.title}`}>
                                    <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
                                        <polygon points="5 3 19 12 5 21 5 3" />
                                    </svg>
                                </div>
                            </a>
                        ))
                    ) : (
                        <div className="sr-video-card sr-video-placeholder">
                            <div className="sr-video-thumb-placeholder" />
                            <div className="sr-video-info">
                                <span className="sr-video-title" style={{ opacity: 0.5 }}>
                                    {videoLoading ? "Searching..." : "Ask something to see related videos"}
                                </span>
                            </div>
                        </div>
                    )}
                </div>
            </div>

            {/* Nearest Stores — Real component with map */}
            <div className="sr-section">
                <h3 className="sr-section-title">Nearest Stores</h3>
                <NearestStores />
            </div>
        </aside>
    );
}

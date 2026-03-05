/**
 * SearchHistory — Left panel showing "Previous Search History"
 * Accepts dynamic items from parent, falls back to placeholder data.
 */

const DEFAULT_ITEMS = [
    { label: "Medicines", pct: 63 },
    { label: "Medical Equipment", pct: 63 },
    { label: "Traffic Signals", pct: 44 },
    { label: "Data Recognition", pct: 44 },
    { label: "Alarm", pct: 43 },
    { label: "Facts", pct: 45 },
    { label: "Phones", pct: 45 },
    { label: "Cartoons", pct: 43 },
    { label: "Restaurants", pct: 41 },
    { label: "Cloth Stores", pct: 49 },
];

export function SearchHistory({ items }) {
    // Use dynamic items if available, otherwise show defaults
    const displayItems = items && items.length > 0 ? items : DEFAULT_ITEMS;

    return (
        <aside className="search-history-panel" id="search-history">
            <h2 className="panel-title">Previous Search History</h2>

            <div className="history-grid">
                {displayItems.map((item, i) => (
                    <div className="history-card" key={item.label || i} id={`history-card-${i}`}>
                        <span className="history-card-label">{item.label}</span>
                        <div className="history-card-stats">
                            <span className="history-card-pct">{item.pct}%</span>
                            {item.count && (
                                <span className="history-card-count">{item.count} searches</span>
                            )}
                        </div>
                        <div className="history-card-bar">
                            <div
                                className="history-card-bar-fill"
                                style={{ width: `${item.pct}%` }}
                            />
                        </div>
                    </div>
                ))}
            </div>

            {/* Scroll indicator */}
            <div className="history-scroll-indicator">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="6 9 12 15 18 9" />
                </svg>
            </div>
        </aside>
    );
}

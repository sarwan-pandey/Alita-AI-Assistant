/**
 * BottomNav — Floating bottom navigation bar with icon buttons.
 */

export function BottomNav() {
    return (
        <nav className="bottom-nav" id="bottom-nav">
            {/* Home */}
            <button className="bottom-nav-btn active" title="Home" id="nav-home">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z" />
                </svg>
            </button>

            {/* Search */}
            <button className="bottom-nav-btn" title="Search" id="nav-search">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="11" cy="11" r="8" />
                    <line x1="21" y1="21" x2="16.65" y2="16.65" />
                </svg>
            </button>

            {/* Send / Chat */}
            <button className="bottom-nav-btn" title="Send" id="nav-send">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <line x1="22" y1="2" x2="11" y2="13" />
                    <polygon points="22 2 15 22 11 13 2 9 22 2" />
                </svg>
            </button>

            {/* Code / Settings */}
            <button className="bottom-nav-btn" title="Code" id="nav-code">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="16 18 22 12 16 6" />
                    <polyline points="8 6 2 12 8 18" />
                </svg>
            </button>
        </nav>
    );
}

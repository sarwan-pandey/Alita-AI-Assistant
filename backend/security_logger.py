"""
security_logger.py — Security Audit Logging & Traffic Anomaly Detection
========================================================================
Provides structured security event logging for:
  1. Authentication events (success/fail/expired)
  2. API errors (4xx/5xx)
  3. Traffic anomalies (burst detection, auth flood, rate limit hits)

All events are logged in JSON format for easy parsing by log aggregators.

Usage:
    from security_logger import sec_log, traffic_monitor

    sec_log.auth_success(user_id="u123", ip="1.2.3.4", method="jwt")
    sec_log.auth_failed(ip="1.2.3.4", reason="invalid_token")
    traffic_monitor.record_request(ip="1.2.3.4")
"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from typing import Any, Dict, Optional

# ── Dedicated security logger ────────────────────────────────────────────────
_sec_logger = logging.getLogger("Alita.security")
_sec_logger.setLevel(logging.INFO)

# Add file handler for security events (separate from main log)
try:
    import os
    _log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    os.makedirs(_log_dir, exist_ok=True)
    _sec_file = logging.FileHandler(
        os.path.join(_log_dir, "security.log"), encoding="utf-8"
    )
    _sec_file.setFormatter(logging.Formatter(
        "%(asctime)s | %(message)s", datefmt="%Y-%m-%dT%H:%M:%S"
    ))
    _sec_logger.addHandler(_sec_file)
except Exception:
    pass  # Fall back to root logger if file creation fails


def _json_event(category: str, event: str, **kwargs: Any) -> str:
    """Build a structured JSON log line."""
    data: Dict[str, Any] = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "category": category,
        "event": event,
    }
    data.update(kwargs)
    return json.dumps(data, default=str)


# ── §1 Authentication Event Logger ───────────────────────────────────────────

class SecurityLogger:
    """Structured security event logger."""

    def auth_success(self, user_id: str, ip: str, method: str = "jwt",
                     tier: str = "", session_id: str = "") -> None:
        """Log successful authentication."""
        _sec_logger.info(_json_event(
            "AUTH", "LOGIN_SUCCESS",
            user_id=user_id, ip=ip, method=method, tier=tier,
            session_id=session_id,
        ))

    def auth_failed(self, ip: str, reason: str, username: str = "",
                    session_id: str = "") -> None:
        """Log failed authentication attempt."""
        _sec_logger.warning(_json_event(
            "AUTH", "LOGIN_FAILED",
            ip=ip, reason=reason, username=username,
            session_id=session_id,
        ))
        # Feed to traffic monitor
        traffic_monitor.record_failed_auth(ip)

    def auth_expired(self, user_id: str, ip: str, session_id: str = "") -> None:
        """Log expired token usage."""
        _sec_logger.info(_json_event(
            "AUTH", "TOKEN_EXPIRED",
            user_id=user_id, ip=ip, session_id=session_id,
        ))

    def ws_connect(self, user_id: str, ip: str, session_id: str = "",
                   tier: str = "") -> None:
        """Log WebSocket connection established."""
        _sec_logger.info(_json_event(
            "AUTH", "WS_CONNECT",
            user_id=user_id, ip=ip, session_id=session_id, tier=tier,
        ))

    def ws_disconnect(self, user_id: str, ip: str, session_id: str = "",
                      reason: str = "") -> None:
        """Log WebSocket disconnect."""
        _sec_logger.info(_json_event(
            "AUTH", "WS_DISCONNECT",
            user_id=user_id, ip=ip, session_id=session_id, reason=reason,
        ))

    # ── API Errors ────────────────────────────────────────────────────────

    def api_error(self, status_code: int, path: str, ip: str,
                  method: str = "GET", detail: str = "",
                  user_id: str = "") -> None:
        """Log API error (4xx/5xx)."""
        level = logging.WARNING if status_code < 500 else logging.ERROR
        _sec_logger.log(level, _json_event(
            "API", "ERROR",
            status_code=status_code, path=path, ip=ip,
            method=method, detail=detail[:200], user_id=user_id,
        ))

    def rate_limited(self, user_id: str, ip: str, tier: str,
                     session_id: str = "") -> None:
        """Log rate limit hit."""
        _sec_logger.warning(_json_event(
            "API", "RATE_LIMITED",
            user_id=user_id, ip=ip, tier=tier, session_id=session_id,
        ))
        traffic_monitor.record_rate_limit(ip)

    # ── Admin actions ─────────────────────────────────────────────────────

    def admin_action(self, action: str, ip: str, detail: str = "") -> None:
        """Log admin endpoint access."""
        _sec_logger.info(_json_event(
            "ADMIN", action,
            ip=ip, detail=detail[:200],
        ))


# ── §2 Traffic Anomaly Monitor ───────────────────────────────────────────────

class TrafficMonitor:
    """
    Detects suspicious traffic patterns per IP:
      - Burst: >30 requests in 60 seconds from single IP
      - Auth flood: >5 failed auth attempts in 60 seconds
      - Rate limit abuse: >10 rate limit hits in 5 minutes
    """

    BURST_THRESHOLD = 30        # requests per minute
    BURST_WINDOW = 60           # seconds
    AUTH_FLOOD_THRESHOLD = 5    # failed auths per minute
    AUTH_FLOOD_WINDOW = 60      # seconds
    RATE_ABUSE_THRESHOLD = 10   # rate limit hits
    RATE_ABUSE_WINDOW = 300     # seconds (5 min)

    def __init__(self) -> None:
        self._requests: Dict[str, list] = defaultdict(list)     # ip → [timestamps]
        self._failed_auths: Dict[str, list] = defaultdict(list) # ip → [timestamps]
        self._rate_limits: Dict[str, list] = defaultdict(list)  # ip → [timestamps]
        self._alerted: Dict[str, float] = {}  # ip → last_alert_timestamp (debounce)

    def _cleanup(self, store: Dict[str, list], window: int) -> None:
        """Remove entries older than window seconds."""
        now = time.time()
        for ip in list(store.keys()):
            store[ip] = [t for t in store[ip] if now - t < window]
            if not store[ip]:
                del store[ip]

    def _should_alert(self, ip: str, alert_type: str, cooldown: int = 300) -> bool:
        """Debounce alerts: max 1 per IP per cooldown period per type."""
        key = f"{ip}:{alert_type}"
        now = time.time()
        last = self._alerted.get(key, 0)
        if now - last < cooldown:
            return False
        self._alerted[key] = now
        return True

    def record_request(self, ip: str) -> None:
        """Record an incoming request and check for burst."""
        now = time.time()
        self._requests[ip].append(now)

        # Clean old entries periodically (every ~100 calls)
        if len(self._requests[ip]) % 100 == 0:
            self._cleanup(self._requests, self.BURST_WINDOW)

        # Check burst
        recent = [t for t in self._requests[ip] if now - t < self.BURST_WINDOW]
        self._requests[ip] = recent

        if len(recent) > self.BURST_THRESHOLD:
            if self._should_alert(ip, "BURST"):
                _sec_logger.warning(_json_event(
                    "ANOMALY", "TRAFFIC_BURST",
                    ip=ip, count=len(recent),
                    window_seconds=self.BURST_WINDOW,
                    message=f"IP {ip} sent {len(recent)} requests in {self.BURST_WINDOW}s",
                ))

    def record_failed_auth(self, ip: str) -> None:
        """Record failed auth attempt and check for auth flood."""
        now = time.time()
        self._failed_auths[ip].append(now)

        recent = [t for t in self._failed_auths[ip] if now - t < self.AUTH_FLOOD_WINDOW]
        self._failed_auths[ip] = recent

        if len(recent) >= self.AUTH_FLOOD_THRESHOLD:
            if self._should_alert(ip, "AUTH_FLOOD"):
                _sec_logger.critical(_json_event(
                    "ANOMALY", "AUTH_FLOOD",
                    ip=ip, count=len(recent),
                    window_seconds=self.AUTH_FLOOD_WINDOW,
                    message=f"IP {ip} had {len(recent)} failed auth attempts in {self.AUTH_FLOOD_WINDOW}s — possible brute force",
                ))

    def record_rate_limit(self, ip: str) -> None:
        """Record rate limit hit and check for abuse."""
        now = time.time()
        self._rate_limits[ip].append(now)

        recent = [t for t in self._rate_limits[ip] if now - t < self.RATE_ABUSE_WINDOW]
        self._rate_limits[ip] = recent

        if len(recent) >= self.RATE_ABUSE_THRESHOLD:
            if self._should_alert(ip, "RATE_ABUSE"):
                _sec_logger.warning(_json_event(
                    "ANOMALY", "RATE_LIMIT_ABUSE",
                    ip=ip, count=len(recent),
                    window_seconds=self.RATE_ABUSE_WINDOW,
                    message=f"IP {ip} hit rate limit {len(recent)} times in {self.RATE_ABUSE_WINDOW}s",
                ))

    def get_stats(self) -> Dict[str, Any]:
        """Get current monitoring stats (for admin dashboard)."""
        now = time.time()
        return {
            "active_ips": len(self._requests),
            "flagged_ips": len(self._alerted),
            "top_requesters": sorted(
                [(ip, len(ts)) for ip, ts in self._requests.items()],
                key=lambda x: x[1], reverse=True,
            )[:10],
        }


# ── Singletons ────────────────────────────────────────────────────────────────
sec_log = SecurityLogger()
traffic_monitor = TrafficMonitor()

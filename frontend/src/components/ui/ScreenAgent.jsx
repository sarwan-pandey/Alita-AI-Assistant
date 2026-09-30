/**
 * ScreenAgent — Floating status indicator for the on-screen agent.
 * Shows progress bar, step counter, auth popup alerts, and stop button.
 */

import { useState, useEffect } from "react";

export function ScreenAgent({ wsStatus }) {
    const [task, setTask] = useState(null);       // { taskId, command, step, total, thought, subIdx, subTotal, replay }
    const [done, setDone] = useState(null);        // "Done" | "Stopped" | "Failed"
    const [authAlert, setAuthAlert] = useState(null); // auth popup message

    const BACKEND = (import.meta.env.VITE_WS_BACKEND_URL || "ws://localhost:8000/ws")
        .replace("ws://", "http://")
        .replace("wss://", "https://")
        .replace("/ws", "");

    useEffect(() => {
        const handler = (e) => {
            try {
                const msg = typeof e.detail === "string" ? JSON.parse(e.detail) : e.detail;

                if (msg.type === "screen_task_started") {
                    setTask({
                        taskId: msg.task_id, command: msg.command,
                        step: 0, total: msg.estimated_steps || 10, thought: "",
                        subIdx: 0, subTotal: 1, replay: msg.replay || false,
                    });
                    setDone(null);
                    setAuthAlert(null);
                }
                if (msg.type === "screen_task_progress") {
                    setTask(prev => prev ? {
                        ...prev,
                        step: msg.step || prev.step,
                        total: msg.estimated_total || prev.total,
                        thought: msg.thought || prev.thought,
                        subIdx: msg.sub_task_index || prev.subIdx,
                        subTotal: msg.sub_task_total || prev.subTotal,
                    } : prev);
                }
                if (msg.type === "screen_task_complete") {
                    setTask(null); setAuthAlert(null);
                    setDone(`✓ Done in ${msg.steps} steps`);
                    setTimeout(() => setDone(null), 4000);
                }
                if (msg.type === "screen_task_stopped") {
                    setTask(null); setAuthAlert(null);
                    setDone("⏹ Stopped");
                    setTimeout(() => setDone(null), 3000);
                }
                if (msg.type === "screen_task_failed") {
                    setTask(null); setAuthAlert(null);
                    setDone(`✕ ${msg.error || "Failed"}`);
                    setTimeout(() => setDone(null), 5000);
                }
                if (msg.type === "screen_task_auth") {
                    setAuthAlert(msg.message || "Login popup detected — please handle it");
                    setTimeout(() => setAuthAlert(null), 30000);
                }
            } catch { /* ignore */ }
        };

        window.addEventListener("Alita:ws_message", handler);
        return () => window.removeEventListener("Alita:ws_message", handler);
    }, []);

    const handleStop = async () => {
        try {
            await fetch(`${BACKEND}/api/screen/stop`, { method: "POST" });
        } catch (e) {
            console.warn("Screen stop error:", e);
        }
    };

    // Nothing to show
    if (!task && !done && !authAlert) return null;

    // Auth alert
    if (authAlert) {
        return (
            <div className="screen-agent-pill screen-agent-auth">
                <span className="screen-agent-auth-icon">🔐</span>
                <span className="screen-agent-label">{authAlert}</span>
            </div>
        );
    }

    // Done toast
    if (!task && done) {
        return (
            <div className="screen-agent-toast">
                <span className="screen-agent-toast-text">{done}</span>
            </div>
        );
    }

    // Active task — progress indicator
    if (!task) return null;

    const pct = task.total > 0 ? Math.min((task.step / task.total) * 100, 100) : 0;

    return (
        <div className="screen-agent-pill">
            <div className="screen-agent-dot" />
            <div className="screen-agent-info">
                <span className="screen-agent-label">
                    {task.replay && "🔁 "}
                    {task.subTotal > 1 && `Sub ${task.subIdx}/${task.subTotal} • `}
                    Step {task.step}/{task.total}
                </span>
                <div className="screen-agent-progress-bar">
                    <div
                        className="screen-agent-progress-fill"
                        style={{ width: `${pct}%` }}
                    />
                </div>
                {task.thought && (
                    <span className="screen-agent-thought">{task.thought.slice(0, 50)}</span>
                )}
            </div>
            <button className="screen-agent-stop" onClick={handleStop} title="Stop">
                ■
            </button>
        </div>
    );
}

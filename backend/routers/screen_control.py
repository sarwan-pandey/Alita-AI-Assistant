"""
Screen Control Router — REST API for the Screen Agent
Supports parallel tasks, task memory, and progress events.
All endpoints require authentication via JWT Bearer token.
"""

from fastapi import APIRouter, HTTPException, Request  # type: ignore[import-untyped]
from pydantic import BaseModel  # type: ignore[import-untyped]
import uuid
import logging
from typing import Any, Optional

from engines.screen_agent import screen_agent, task_manager  # type: ignore[import]
from engines.task_memory import task_memory as tmem  # type: ignore[import]

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/screen", tags=["screen"])


class TaskRequest(BaseModel):
    command: str
    parallel: bool = False  # If True, use TaskManager for parallel execution


class TaskResponse(BaseModel):
    task_id: str
    status: str
    message: str


# ── Start Task ───────────────────────────────────────────────────────────────
@router.post("/task", response_model=TaskResponse)
async def start_screen_task(req: TaskRequest, request: Request) -> Any:
    """Start a screen automation task (single or parallel). Requires auth."""
    from auth_deps import require_auth  # type: ignore[import]
    await require_auth(request)

    task_id = str(uuid.uuid4())[:8]

    if req.parallel:
        started = task_manager.start_task(task_id, req.command)
        if not started:
            raise HTTPException(409, f"Max {3} parallel tasks reached or failed to start")
    else:
        if screen_agent.is_running:
            raise HTTPException(409, "A screen task is already running")
        started = screen_agent.start_task(task_id, req.command)

    if not started:
        raise HTTPException(500, "Failed to start screen task")

    return TaskResponse(task_id=task_id, status="started", message=f"Task started: {req.command}")


# ── Stop Task ────────────────────────────────────────────────────────────────
@router.post("/stop")
async def stop_screen_task(request: Request, task_id: Optional[str] = None) -> dict:  # type: ignore[type-arg]
    """Stop a task. Requires auth."""
    from auth_deps import require_auth  # type: ignore[import]
    await require_auth(request)

    if task_id:
        if task_manager.stop_task(task_id):
            return {"status": "stopping", "message": f"Stop requested for task {task_id}"}
        return {"status": "not_found", "message": f"No running task with id {task_id}"}

    if not screen_agent.is_running:
        return {"status": "idle", "message": "No task running"}
    screen_agent.stop_task()
    return {"status": "stopping", "message": "Stop requested"}


@router.post("/stop-all")
async def stop_all_tasks(request: Request) -> dict:  # type: ignore[type-arg]
    """Stop all running tasks. Requires auth."""
    from auth_deps import require_auth  # type: ignore[import]
    await require_auth(request)

    screen_agent.stop_task()
    task_manager.stop_all()
    return {"status": "stopping", "message": "All tasks stop requested"}


# ── Status ───────────────────────────────────────────────────────────────────
@router.get("/status")
async def get_screen_status(request: Request) -> dict:  # type: ignore[type-arg]
    """Get status of all running tasks. Requires auth."""
    from auth_deps import require_auth  # type: ignore[import]
    await require_auth(request)

    return {
        "default_agent": {
            "running": screen_agent.is_running,
            "task_id": screen_agent.current_task_id,
            "steps_taken": screen_agent.steps_taken,
        },
        "parallel_tasks": task_manager.get_status(),
        "running_count": task_manager.running_count + (1 if screen_agent.is_running else 0),
    }


# ── Windows ──────────────────────────────────────────────────────────────────
@router.get("/windows")
async def get_open_windows(request: Request) -> dict:  # type: ignore[type-arg]
    """List open windows. Requires auth."""
    from auth_deps import require_auth  # type: ignore[import]
    await require_auth(request)

    from engines.app_manager import list_windows  # type: ignore[import]
    windows = list_windows()
    return {"windows": windows, "count": len(windows)}


# ── Task History ─────────────────────────────────────────────────────────────
@router.get("/history")
async def get_task_history(request: Request, limit: int = 10) -> dict:  # type: ignore[type-arg]
    """List recent task history. Requires auth."""
    from auth_deps import require_auth  # type: ignore[import]
    await require_auth(request)

    return {"tasks": tmem.list_tasks(limit)}


@router.get("/history/search")
async def search_task_history(request: Request, q: str) -> dict:  # type: ignore[type-arg]
    """Search past tasks by command similarity. Requires auth."""
    from auth_deps import require_auth  # type: ignore[import]
    await require_auth(request)

    return {"results": tmem.find_similar(q)}

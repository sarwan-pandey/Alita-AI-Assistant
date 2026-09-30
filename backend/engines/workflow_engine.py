"""
Workflow Engine — Multi-step autonomous task execution.

Handles complex workflows with:
  - Sequential step execution
  - Conditional logic (if/else branching)
  - Retry loops (e.g., refine until score >= 95)
  - User checkpoints (pause and ask before proceeding)
  - Progress notifications via WebSocket
  - Stop event integration for instant interrupt

Usage:
    engine = WorkflowEngine(notify_fn=ws_notify, stop_event=stop)
    result = await engine.run(BlogPublishWorkflow, params={
        "topic": "AI in healthcare",
        "platform": "blogger",
    })
"""

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("alita.workflow")


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"
    WAITING = "waiting"  # Waiting for user input


@dataclass
class StepResult:
    """Result of a workflow step execution."""
    success: bool
    message: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    skip_next: int = 0  # Number of steps to skip (for branching)


@dataclass
class WorkflowResult:
    """Final result of a complete workflow."""
    success: bool
    message: str
    steps_completed: int = 0
    total_steps: int = 0
    data: Dict[str, Any] = field(default_factory=dict)
    elapsed_ms: float = 0


class WorkflowStep(ABC):
    """Base class for a workflow step."""

    name: str = "Unnamed Step"
    description: str = ""
    retries: int = 0  # Max retry attempts
    timeout_s: int = 60  # Step timeout in seconds

    @abstractmethod
    async def execute(self, context: Dict[str, Any]) -> StepResult:
        """
        Execute this step.

        Args:
            context: Shared workflow context (params, browser page, etc.)

        Returns:
            StepResult with success flag and optional data to merge into context.
        """
        ...


class ConditionalStep(WorkflowStep):
    """Step that branches based on a condition."""

    async def execute(self, context: Dict[str, Any]) -> StepResult:
        condition = await self.check(context)
        if condition:
            return await self.on_true(context)
        else:
            return await self.on_false(context)

    @abstractmethod
    async def check(self, context: Dict[str, Any]) -> bool:
        ...

    async def on_true(self, context: Dict[str, Any]) -> StepResult:
        return StepResult(success=True, message="Condition met")

    async def on_false(self, context: Dict[str, Any]) -> StepResult:
        return StepResult(success=True, message="Condition not met")


class LoopStep(WorkflowStep):
    """Step that repeats until a condition is met."""

    max_iterations: int = 5

    async def execute(self, context: Dict[str, Any]) -> StepResult:
        result: Optional[StepResult] = None
        for i in range(self.max_iterations):
            result = await self.loop_body(context)
            if await self.should_stop(context, result):
                return StepResult(
                    success=True,
                    message=f"Loop completed after {i+1} iterations",
                    data=result.data,
                )
            logger.info(f"[Workflow] Loop iteration {i+1}/{self.max_iterations}")

        return StepResult(
            success=True,
            message=f"Loop reached max iterations ({self.max_iterations})",
            data=result.data if result else {},
        )

    @abstractmethod
    async def loop_body(self, context: Dict[str, Any]) -> StepResult:
        ...

    @abstractmethod
    async def should_stop(self, context: Dict[str, Any], result: StepResult) -> bool:
        ...


class CheckpointStep(WorkflowStep):
    """Step that pauses execution and asks user for confirmation."""

    message_template: str = "Continue?"

    async def execute(self, context: Dict[str, Any]) -> StepResult:
        message = self.message_template.format(**context)
        notify = context.get("_notify_fn")
        if notify:
            notify({
                "type": "workflow_checkpoint",
                "message": message,
                "requires_response": True,
            })
        # For now, auto-continue. Future: wait for WebSocket response
        logger.info(f"[Workflow] Checkpoint: {message}")
        return StepResult(success=True, message=f"Checkpoint: {message}")


class BaseWorkflow(ABC):
    """Base class for a workflow definition."""

    name: str = "Unnamed Workflow"
    description: str = ""

    @abstractmethod
    def get_steps(self) -> List[WorkflowStep]:
        """Return the ordered list of steps for this workflow."""
        ...


class WorkflowEngine:
    """
    Executes multi-step workflows with progress notifications,
    error recovery, and stop event support.
    """

    def __init__(
        self,
        notify_fn: Optional[Callable] = None,
        stop_event: Optional[Any] = None,
    ):
        self.notify = notify_fn or (lambda data: None)
        self.stop_event = stop_event

    def _stopped(self) -> bool:
        """Check if stop was requested."""
        if self.stop_event is None:
            return False
        if hasattr(self.stop_event, "is_set"):
            return self.stop_event.is_set()
        return False

    async def run(
        self,
        workflow: BaseWorkflow,
        params: Dict[str, Any],
    ) -> WorkflowResult:
        """
        Execute a complete workflow.

        Args:
            workflow: The workflow definition (list of steps)
            params: User-provided parameters (topic, platform, etc.)

        Returns:
            WorkflowResult with success/failure and execution data.
        """
        steps = workflow.get_steps()
        total = len(steps)
        t0 = time.time()

        # Build shared context — steps can read/write to this
        context: Dict[str, Any] = {
            **params,
            "_notify_fn": self.notify,
            "_stop_event": self.stop_event,
            "_results": [],
        }

        logger.info(f"[Workflow] Starting '{workflow.name}' with {total} steps")
        self.notify({
            "type": "workflow_started",
            "workflow": workflow.name,
            "total_steps": total,
        })

        completed = 0
        skip_remaining = 0  # Track steps to skip (for branching)
        for i, step in enumerate(steps):
            # Handle skip_next from previous step's branching
            if skip_remaining > 0:
                logger.info(f"[Workflow] Skipping step {i+1}: {step.name} (branch skip)")
                skip_remaining -= 1
                continue

            if self._stopped():
                logger.info(f"[Workflow] Stopped at step {i+1}")
                return WorkflowResult(
                    success=False,
                    message=f"Stopped at step {i+1}: {step.name}",
                    steps_completed=completed,
                    total_steps=total,
                    elapsed_ms=(time.time() - t0) * 1000,
                )

            logger.info(f"[Workflow] Step {i+1}/{total}: {step.name}")
            self.notify({
                "type": "workflow_step",
                "step": i + 1,
                "total": total,
                "name": step.name,
                "description": step.description,
            })

            try:
                result = await asyncio.wait_for(
                    step.execute(context),
                    timeout=step.timeout_s,
                )
            except asyncio.TimeoutError:
                logger.error(f"[Workflow] Step '{step.name}' timed out after {step.timeout_s}s")
                # Retry if configured
                if step.retries > 0:
                    for retry in range(step.retries):
                        logger.info(f"[Workflow] Retry {retry+1}/{step.retries} for '{step.name}'")
                        try:
                            result = await asyncio.wait_for(
                                step.execute(context),
                                timeout=step.timeout_s,
                            )
                            if result.success:
                                break
                        except asyncio.TimeoutError:
                            continue
                    else:
                        return WorkflowResult(
                            success=False,
                            message=f"Step '{step.name}' failed after {step.retries} retries",
                            steps_completed=completed,
                            total_steps=total,
                            elapsed_ms=(time.time() - t0) * 1000,
                        )
                else:
                    return WorkflowResult(
                        success=False,
                        message=f"Step '{step.name}' timed out",
                        steps_completed=completed,
                        total_steps=total,
                        elapsed_ms=(time.time() - t0) * 1000,
                    )
            except Exception as e:
                logger.error(f"[Workflow] Step '{step.name}' error: {e}")
                return WorkflowResult(
                    success=False,
                    message=f"Step '{step.name}' failed: {e}",
                    steps_completed=completed,
                    total_steps=total,
                    data=context,
                    elapsed_ms=(time.time() - t0) * 1000,
                )

            if not result.success:
                logger.warning(f"[Workflow] Step '{step.name}' failed: {result.message}")
                return WorkflowResult(
                    success=False,
                    message=f"Step '{step.name}': {result.message}",
                    steps_completed=completed,
                    total_steps=total,
                    data=context,
                    elapsed_ms=(time.time() - t0) * 1000,
                )

            # Merge step results into context
            if result.data:
                context.update(result.data)
            context["_results"].append({
                "step": step.name,
                "message": result.message,
            })

            completed += 1

            # Handle skip (for branching)
            if result.skip_next > 0:
                skip_remaining = result.skip_next
                logger.info(f"[Workflow] Skipping next {result.skip_next} steps")

            self.notify({
                "type": "workflow_step_done",
                "step": i + 1,
                "message": result.message,
            })

        elapsed = (time.time() - t0) * 1000
        logger.info(f"[Workflow] '{workflow.name}' completed in {elapsed:.0f}ms")

        self.notify({
            "type": "workflow_completed",
            "workflow": workflow.name,
            "steps_completed": completed,
            "elapsed_ms": elapsed,
        })

        return WorkflowResult(
            success=True,
            message=f"Workflow '{workflow.name}' completed successfully",
            steps_completed=completed,
            total_steps=total,
            data=context,
            elapsed_ms=elapsed,
        )

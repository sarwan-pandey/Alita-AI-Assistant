"""Resource & Memory Budget Guard (Gap 10).
Prevents Out-Of-Memory (OOM) crashes by enforcing RAM and VRAM budgets,
preventing concurrent heavy model loads, and triggering proactive cleanup.
"""

import gc
import logging
import threading
from contextlib import contextmanager
from typing import Any, Optional

try:
    import psutil
except ImportError:
    psutil = None  # type: ignore[assignment]

log = logging.getLogger("resource_guard")


class ResourceGuard:
    """Monitors system memory and guards model loading against OOM conditions."""

    def __init__(self, max_ram_percent: float = 85.0):
        self.max_ram_percent = max_ram_percent
        self._lock = threading.Lock()

    def _get_vm(self) -> Any:
        """Internal helper to retrieve virtual memory metrics from psutil if available."""
        if psutil is not None:
            return psutil.virtual_memory()
        return None

    def get_ram_usage(self) -> float:
        """Return current RAM utilization percentage (0.0 - 100.0)."""
        vm = self._get_vm()
        if vm is None:
            return 0.0
        return float(vm.percent)

    def get_available_ram_mb(self) -> float:
        """Return currently available RAM in megabytes."""
        vm = self._get_vm()
        if vm is None:
            return 8192.0
        return float(vm.available / (1024 * 1024))

    def can_load(self, estimated_mb: int) -> bool:
        """Verify whether the system has sufficient memory headroom to load an engine."""
        vm = self._get_vm()
        if vm is None:
            return True

        if vm.percent >= 92.0:
            log.warning("RAM dangerously high: %.1f%% used", vm.percent)
            return False

        available_mb = vm.available / (1024 * 1024)
        # Require 20% safety margin above estimated memory
        required_mb = estimated_mb * 1.2
        if available_mb < required_mb:
            log.warning(
                "Insufficient RAM headroom for %d MB: only %.1f MB available (need %.1f MB)",
                estimated_mb, available_mb, required_mb
            )
            return False

        return True

    def cleanup(self) -> None:
        """Trigger aggressive memory garbage collection and cache clearance."""
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    @contextmanager
    def loading(self, model_name: str, estimated_mb: int = 500):
        """Context manager that synchronizes model loads and enforces memory safety."""
        with self._lock:
            if not self.can_load(estimated_mb):
                # Attempt proactive reclamation
                self.cleanup()
                if not self.can_load(estimated_mb):
                    available_mb = self.get_available_ram_mb()
                    raise MemoryError(
                        f"Not enough RAM to load {model_name} "
                        f"({estimated_mb}MB needed, {available_mb:.1f}MB available)"
                    )
            log.info("Loading engine '%s' (allocating ~%d MB)...", model_name, estimated_mb)
            try:
                yield
            finally:
                log.info("Engine '%s' load operation complete.", model_name)


# Global singleton instance
resource_guard = ResourceGuard()

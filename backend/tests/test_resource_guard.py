"""Unit tests for Gap 10: VRAM/RAM Budget Guard (test_resource_guard.py).
Tests RAM usage queries, threshold validation, mutex synchronization, and error handling.
"""

import threading
import time
from unittest.mock import MagicMock, patch
import pytest


def test_ram_check_returns_value():
    from engines.resource_guard import ResourceGuard
    guard = ResourceGuard()
    usage = guard.get_ram_usage()
    assert isinstance(usage, float)
    assert 0.0 <= usage <= 100.0


def test_guard_blocks_when_full():
    from engines.resource_guard import ResourceGuard
    guard = ResourceGuard()

    # Mock available RAM to only 100 MB (not enough for 200 MB with 20% margin = 240 MB)
    mock_vm = MagicMock()
    mock_vm.available = 100 * 1024 * 1024
    mock_vm.percent = 95.0

    with patch.object(guard, "_get_vm", return_value=mock_vm):
        assert guard.can_load(estimated_mb=200) is False


def test_guard_allows_when_free():
    from engines.resource_guard import ResourceGuard
    guard = ResourceGuard()

    # Mock available RAM to 8192 MB (ample space for 500 MB)
    mock_vm = MagicMock()
    mock_vm.available = 8192 * 1024 * 1024
    mock_vm.percent = 50.0

    with patch.object(guard, "_get_vm", return_value=mock_vm):
        assert guard.can_load(estimated_mb=500) is True


def test_loading_context_manager_raises_memory_error():
    from engines.resource_guard import ResourceGuard
    guard = ResourceGuard()

    mock_vm = MagicMock()
    mock_vm.available = 50 * 1024 * 1024  # 50 MB
    mock_vm.percent = 96.0

    with patch.object(guard, "_get_vm", return_value=mock_vm):
        with pytest.raises(MemoryError, match="Not enough RAM to load HeavyModel"):
            with guard.loading("HeavyModel", estimated_mb=1000):
                pass


def test_concurrent_load_mutex():
    from engines.resource_guard import ResourceGuard
    guard = ResourceGuard()

    # Ample RAM
    mock_vm = MagicMock()
    mock_vm.available = 16384 * 1024 * 1024
    mock_vm.percent = 30.0

    concurrent_count = 0
    max_concurrent = 0
    lock = threading.Lock()

    def worker():
        nonlocal concurrent_count, max_concurrent
        with patch.object(guard, "_get_vm", return_value=mock_vm):
            with guard.loading("TestModel", estimated_mb=100):
                with lock:
                    concurrent_count += 1
                    if concurrent_count > max_concurrent:
                        max_concurrent = concurrent_count
                time.sleep(0.05)
                with lock:
                    concurrent_count -= 1

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert max_concurrent == 1, f"Expected mutex lock to allow only 1 concurrent load, observed {max_concurrent}"

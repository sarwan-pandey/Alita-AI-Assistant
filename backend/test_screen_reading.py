"""
test_screen_reading.py — Test Screen Perception (view-tree extraction and fallback)
"""

import asyncio
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from engines.phone_orchestrator import PhoneOrchestrator


def test_screen_reading_node_extraction():
    """Test 3: read_screen on known app returns expected element text and resource IDs."""
    sample_tree = {
        "package": "com.whatsapp",
        "nodes": [
            {
                "id": "com.whatsapp:id/menuitem_search",
                "text": "Search",
                "contentDesc": "Search",
                "isClickable": True,
                "bounds": {"left": 800, "top": 50, "right": 900, "bottom": 120, "cx": 850, "cy": 85},
            },
            {
                "id": "com.whatsapp:id/conversations_row_contact_name",
                "text": "Rahul",
                "contentDesc": "Rahul",
                "isClickable": True,
                "bounds": {"left": 100, "top": 200, "right": 700, "bottom": 280, "cx": 400, "cy": 240},
            },
        ]
    }

    po = PhoneOrchestrator()
    po.device_info["connected"] = True

    async def mock_sender(cmd_dict, timeout=8.0):
        if cmd_dict.get("command") == "read_screen":
            return {"success": True, "data": sample_tree}
        return {"success": False}

    po.set_bridge_sender(mock_sender)

    tree = asyncio.run(po.read_screen())
    assert tree.get("package") == "com.whatsapp"
    assert len(tree.get("nodes", [])) == 2

    # Verify fuzzy search
    node = po.find_node(tree, query="Search")
    assert node is not None
    assert node["bounds"]["cx"] == 850

    contact_node = po.find_node(tree, query="Rahul")
    assert contact_node is not None
    assert contact_node["text"] == "Rahul"

    print("✅ Test 3 Passed: Screen perception successfully parsed nodes, IDs, and bounding coordinates")


def test_screen_reading_fallback():
    """Test 4: Fallback path when read_screen is sparse or returns empty."""
    po = PhoneOrchestrator()
    po.device_info["connected"] = True

    dump_called = False

    async def mock_sender(cmd_dict, timeout=8.0):
        nonlocal dump_called
        if cmd_dict.get("command") == "read_screen":
            # Sparse or missing data
            return {"success": False, "error": "Accessibility tree sparse"}
        if cmd_dict.get("command") == "dump_tree":
            dump_called = True
            return {"success": True, "data": {"package": "com.android.fallback", "nodes": []}}
        return {"success": False}

    po.set_bridge_sender(mock_sender)

    tree = asyncio.run(po.read_screen())
    assert dump_called is True
    assert tree.get("package") == "com.android.fallback"
    print("✅ Test 4 Passed: Automatic fallback invoked when read_screen was sparse")


def test_tricky_fuzzy_search_content_desc_and_clickable_filter():
    """Tricky 1: find_node prioritizes clickable button matching contentDesc over non-clickable text."""
    tree = {
        "package": "com.whatsapp",
        "nodes": [
            # Non-clickable header containing "Search"
            {"text": "Search your chats and messages", "isClickable": False},
            # Clickable search icon with empty text and contentDesc
            {"text": "", "contentDesc": "Search", "isClickable": True, "bounds": {"cx": 850, "cy": 100}},
        ]
    }

    po = PhoneOrchestrator()
    # Looking for clickable search
    node = po.find_node(tree, query="Search", clickable_only=True)
    assert node is not None
    assert node["isClickable"] is True
    assert node["contentDesc"] == "Search"
    assert node["bounds"]["cx"] == 850
    print("✅ Tricky Test 1 Passed: Fuzzy node search matched clickable contentDesc over non-clickable header")


def test_tricky_disconnected_device_safety():
    """Tricky 2: Disconnected device returns safe empty structure without throwing."""
    po = PhoneOrchestrator()
    po.device_info["connected"] = False

    tree = asyncio.run(po.read_screen())
    assert isinstance(tree, dict)
    assert len(tree.get("nodes", [])) == 0
    print("✅ Tricky Test 2 Passed: Disconnected device read_screen handled safely")


def test_tricky_malformed_nodes_resilience():
    """Tricky 3: View-tree containing None, string nodes, or missing fields does not crash find_node."""
    tree = {
        "package": "com.something",
        "nodes": [None, "invalid_str", {"text": None, "contentDesc": None}, {"text": "Target Node", "isClickable": True}]
    }
    po = PhoneOrchestrator()
    res = po.find_node(tree, query="Target")
    assert res is not None
    assert res["text"] == "Target Node"
    print("✅ Tricky Test 3 Passed: find_node resilient against malformed nodes in view-tree")


if __name__ == "__main__":
    test_screen_reading_node_extraction()
    test_screen_reading_fallback()
    test_tricky_fuzzy_search_content_desc_and_clickable_filter()
    test_tricky_disconnected_device_safety()
    test_tricky_malformed_nodes_resilience()
    print("\n🎉 ALL 5 SCREEN READING TESTS (INCLUDING TRICKY TESTS) PASSED!")

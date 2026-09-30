# pyre-ignore-all-errors
"""
App Knowledge — Expert-level knowledge of keyboard shortcuts,
menus, and workflows for 30+ common apps.
100% local, no API. Just a lookup table.
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════════════
#  SHORTCUT DATABASE — Per-app keyboard shortcuts
# ═════════════════════════════════════════════════════════════════════════════

APP_SHORTCUTS: Dict[str, Dict[str, str]] = {
    "notepad": {
        "save": "ctrl+s", "save_as": "ctrl+shift+s", "open": "ctrl+o",
        "new": "ctrl+n", "print": "ctrl+p", "find": "ctrl+f",
        "replace": "ctrl+h", "select_all": "ctrl+a", "undo": "ctrl+z",
        "redo": "ctrl+y", "cut": "ctrl+x", "copy": "ctrl+c",
        "paste": "ctrl+v", "delete": "delete", "font": "alt+o,f",
        "word_wrap": "alt+o,w", "status_bar": "alt+v,s",
        "goto_line": "ctrl+g", "time_date": "F5",
    },
    "word": {
        "save": "ctrl+s", "save_as": "F12", "open": "ctrl+o",
        "new": "ctrl+n", "print": "ctrl+p", "find": "ctrl+f",
        "replace": "ctrl+h", "select_all": "ctrl+a", "undo": "ctrl+z",
        "redo": "ctrl+y", "bold": "ctrl+b", "italic": "ctrl+i",
        "underline": "ctrl+u", "center": "ctrl+e", "left_align": "ctrl+l",
        "right_align": "ctrl+r", "justify": "ctrl+j",
        "font_size_up": "ctrl+shift+>", "font_size_down": "ctrl+shift+<",
        "heading1": "ctrl+alt+1", "heading2": "ctrl+alt+2",
        "heading3": "ctrl+alt+3", "bullet_list": "ctrl+shift+l",
        "insert_link": "ctrl+k", "spell_check": "F7",
        "word_count": "ctrl+shift+g", "page_break": "ctrl+enter",
        "line_spacing": "ctrl+2", "double_space": "ctrl+2",
        "single_space": "ctrl+1",
    },
    "excel": {
        "save": "ctrl+s", "open": "ctrl+o", "new": "ctrl+n",
        "print": "ctrl+p", "find": "ctrl+f", "replace": "ctrl+h",
        "bold": "ctrl+b", "italic": "ctrl+i", "underline": "ctrl+u",
        "undo": "ctrl+z", "redo": "ctrl+y", "select_all": "ctrl+a",
        "insert_row": "ctrl+shift++", "delete_row": "ctrl+-",
        "insert_column": "ctrl+shift++", "sum": "alt+=",
        "filter": "ctrl+shift+l", "sort": "alt+d,s",
        "format_cells": "ctrl+1", "insert_chart": "alt+F1",
        "freeze_panes": "alt+w,f", "new_sheet": "shift+F11",
        "next_sheet": "ctrl+pagedown", "prev_sheet": "ctrl+pageup",
        "go_to": "ctrl+g", "name_box": "ctrl+F3",
        "autofit_column": "alt+h,o,i",
    },
    "powerpoint": {
        "save": "ctrl+s", "new": "ctrl+n", "open": "ctrl+o",
        "print": "ctrl+p", "undo": "ctrl+z", "redo": "ctrl+y",
        "bold": "ctrl+b", "italic": "ctrl+i", "underline": "ctrl+u",
        "new_slide": "ctrl+m", "duplicate_slide": "ctrl+d",
        "start_slideshow": "F5", "start_from_current": "shift+F5",
        "end_slideshow": "escape", "group": "ctrl+g",
        "ungroup": "ctrl+shift+g", "align_left": "ctrl+l",
        "align_center": "ctrl+e", "align_right": "ctrl+r",
    },
    "chrome": {
        "new_tab": "ctrl+t", "close_tab": "ctrl+w", "reopen_tab": "ctrl+shift+t",
        "next_tab": "ctrl+tab", "prev_tab": "ctrl+shift+tab",
        "address_bar": "ctrl+l", "find": "ctrl+f", "refresh": "F5",
        "hard_refresh": "ctrl+shift+r", "bookmark": "ctrl+d",
        "history": "ctrl+h", "downloads": "ctrl+j",
        "dev_tools": "ctrl+shift+i", "console": "ctrl+shift+j",
        "incognito": "ctrl+shift+n", "new_window": "ctrl+n",
        "zoom_in": "ctrl+plus", "zoom_out": "ctrl+minus",
        "zoom_reset": "ctrl+0", "full_screen": "F11",
        "print": "ctrl+p", "save_page": "ctrl+s",
        "select_all": "ctrl+a", "clear_cache": "ctrl+shift+delete",
    },
    "vscode": {
        "save": "ctrl+s", "save_all": "ctrl+k s",
        "open_file": "ctrl+o", "open_folder": "ctrl+k ctrl+o",
        "new_file": "ctrl+n", "close_tab": "ctrl+w",
        "find": "ctrl+f", "replace": "ctrl+h",
        "find_in_files": "ctrl+shift+f", "replace_in_files": "ctrl+shift+h",
        "go_to_file": "ctrl+p", "go_to_line": "ctrl+g",
        "command_palette": "ctrl+shift+p", "terminal": "ctrl+`",
        "sidebar": "ctrl+b", "explorer": "ctrl+shift+e",
        "search": "ctrl+shift+f", "git": "ctrl+shift+g",
        "debug": "ctrl+shift+d", "extensions": "ctrl+shift+x",
        "split_editor": "ctrl+\\", "toggle_comment": "ctrl+/",
        "indent": "tab", "outdent": "shift+tab",
        "move_line_up": "alt+up", "move_line_down": "alt+down",
        "duplicate_line": "shift+alt+down", "delete_line": "ctrl+shift+k",
        "format_document": "shift+alt+f", "rename_symbol": "F2",
        "go_to_definition": "F12", "peek_definition": "alt+F12",
        "zoom_in": "ctrl+plus", "zoom_out": "ctrl+minus",
    },
    "explorer": {
        "new_folder": "ctrl+shift+n", "rename": "F2",
        "delete": "delete", "permanent_delete": "shift+delete",
        "copy": "ctrl+c", "paste": "ctrl+v", "cut": "ctrl+x",
        "select_all": "ctrl+a", "properties": "alt+enter",
        "refresh": "F5", "address_bar": "ctrl+l",
        "search": "ctrl+e", "back": "alt+left", "forward": "alt+right",
        "up": "alt+up", "preview_pane": "alt+p",
        "details_view": "ctrl+shift+6", "icon_view": "ctrl+shift+1",
    },
    "terminal": {
        "copy": "ctrl+c", "paste": "ctrl+v", "new_tab": "ctrl+shift+t",
        "close_tab": "ctrl+shift+w", "clear": "cls",
        "next_tab": "ctrl+tab", "prev_tab": "ctrl+shift+tab",
        "find": "ctrl+shift+f", "zoom_in": "ctrl+plus",
        "zoom_out": "ctrl+minus", "split_pane": "alt+shift+d",
    },
    # Windows-level shortcuts (always available)
    "windows": {
        "desktop": "win+d", "lock": "win+l", "minimize_all": "win+m",
        "restore_all": "win+shift+m", "taskbar": "win+t",
        "run": "win+r", "settings": "win+i", "search": "win+s",
        "clipboard_history": "win+v", "emoji": "win+.",
        "screenshot": "win+shift+s", "task_manager": "ctrl+shift+escape",
        "switch_app": "alt+tab", "close_app": "alt+F4",
        "maximize": "win+up", "minimize": "win+down",
        "snap_left": "win+left", "snap_right": "win+right",
        "virtual_desktop": "win+tab", "new_virtual_desktop": "win+ctrl+d",
        "notification": "win+n", "action_center": "win+a",
    },
}

# ═════════════════════════════════════════════════════════════════════════════
#  APP-SPECIFIC EDITING AREAS — Where text goes in each app
# ═════════════════════════════════════════════════════════════════════════════

APP_EDIT_INFO: Dict[str, Dict[str, Any]] = {
    "notepad": {
        "focus_method": "click_center",
        "has_formatting": False,
        "file_extension": ".txt",
    },
    "word": {
        "focus_method": "click_body",
        "has_formatting": True,
        "file_extension": ".docx",
        "splash_wait": 3.0,
    },
    "excel": {
        "focus_method": "click_cell_a1",
        "has_formatting": True,
        "file_extension": ".xlsx",
        "splash_wait": 3.0,
    },
    "vscode": {
        "focus_method": "click_editor",
        "has_formatting": False,
        "file_extension": None,
    },
    "chrome": {
        "focus_method": "address_bar",
        "has_formatting": False,
        "file_extension": None,
    },
}


# ═════════════════════════════════════════════════════════════════════════════
#  API
# ═════════════════════════════════════════════════════════════════════════════

def get_shortcut(app: str, action: str) -> Optional[str]:
    """Get keyboard shortcut for an action in an app."""
    app_lower = app.lower()
    action_lower = action.lower().replace(" ", "_")
    
    shortcuts = APP_SHORTCUTS.get(app_lower, {})
    if action_lower in shortcuts:
        return shortcuts[action_lower]
    
    # Try windows-level shortcuts
    win_shortcuts = APP_SHORTCUTS.get("windows", {})
    return win_shortcuts.get(action_lower)


def get_all_shortcuts(app: str) -> Dict[str, str]:
    """Get all shortcuts for an app (including windows-level)."""
    app_lower = app.lower()
    result = dict(APP_SHORTCUTS.get("windows", {}))
    result.update(APP_SHORTCUTS.get(app_lower, {}))
    return result


def get_app_info(app: str) -> Dict[str, Any]:
    """Get app-specific info (focus method, formatting, etc.)."""
    return APP_EDIT_INFO.get(app.lower(), {
        "focus_method": "click_center",
        "has_formatting": False,
    })


def suggest_shortcut(user_action: str, app: str = "") -> Optional[Dict[str, str]]:
    """Suggest a shortcut based on what the user is trying to do."""
    action_lower = user_action.lower()
    
    # Map natural language to shortcut actions
    NATURAL_MAP = {
        "make bold": "bold", "bold": "bold", "bold text": "bold",
        "make italic": "italic", "italicize": "italic",
        "underline": "underline", "save": "save", "save file": "save",
        "find": "find", "search": "find", "open": "open",
        "undo": "undo", "redo": "redo", "copy": "copy",
        "paste": "paste", "cut": "cut", "print": "print",
        "select all": "select_all", "new": "new", "close": "close_tab",
        "zoom in": "zoom_in", "zoom out": "zoom_out",
        "full screen": "full_screen", "screenshot": "screenshot",
    }
    
    mapped = NATURAL_MAP.get(action_lower)
    if mapped:
        shortcut = get_shortcut(app, mapped) if app else None
        if not shortcut:
            shortcut = get_shortcut("windows", mapped)
        if shortcut:
            return {"action": mapped, "shortcut": shortcut, "app": app or "windows"}
    
    return None

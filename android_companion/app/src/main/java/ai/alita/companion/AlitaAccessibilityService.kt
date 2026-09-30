package ai.alita.companion

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Path
import android.graphics.Rect
import android.os.Build
import android.os.Bundle
import android.util.Log
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import android.view.accessibility.AccessibilityWindowInfo

/**
 * AlitaAccessibilityService
 * Core automation engine for Android that dispatches gestures, extracts view-trees,
 * focuses/enters text, and triggers global navigation.
 */
class AlitaAccessibilityService : AccessibilityService() {

    companion object {
        private const val TAG = "AlitaA11y"
        var instance: AlitaAccessibilityService? = null
            private set

        val isRunning: Boolean
            get() = instance != null

        // Bug 8 Fix: Transient overlay / keyboard packages that should never reset active app tracking
        private val TRANSIENT_PACKAGES = setOf(
            "com.google.android.inputmethod.latin",
            "com.android.systemui",
            "com.samsung.android.honeyboard",
            "android",
            "com.google.android.permissioncontroller"
        )
    }

    var currentPackage: String = ""
        private set

    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
        Log.i(TAG, "Alita Accessibility Service Connected and Active")
        AlitaPhoneBridgeService.instance?.notifyStatus("A11Y_CONNECTED")
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (event == null) return
        val pkg = event.packageName?.toString() ?: return
        if (pkg.isNotBlank() && pkg !in TRANSIENT_PACKAGES) {
            val isWindowChange = (event.eventType == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED)
            if (isWindowChange && pkg != currentPackage) {
                currentPackage = pkg
                AlitaPhoneBridgeService.instance?.notifyAppSwitched(pkg)
            }
        }
    }

    override fun onInterrupt() {
        Log.w(TAG, "Alita Accessibility Service Interrupted")
    }

    override fun onDestroy() {
        super.onDestroy()
        if (instance == this) {
            instance = null
        }
        Log.i(TAG, "Alita Accessibility Service Destroyed")
    }

    // ==========================================
    // GESTURE DISPATCH ENGINE
    // ==========================================

    fun dispatchTap(x: Float, y: Float, durationMs: Long = 50, callback: ((Boolean) -> Unit)? = null) {
        val path = Path().apply {
            moveTo(x, y)
        }
        val stroke = GestureDescription.StrokeDescription(path, 0, durationMs.coerceAtLeast(10))
        val gesture = GestureDescription.Builder().addStroke(stroke).build()

        dispatchGesture(gesture, object : GestureResultCallback() {
            override fun onCompleted(gestureDescription: GestureDescription?) {
                Log.d(TAG, "Tap executed at ($x, $y)")
                callback?.invoke(true)
            }

            override fun onCancelled(gestureDescription: GestureDescription?) {
                Log.w(TAG, "Tap cancelled at ($x, $y)")
                callback?.invoke(false)
            }
        }, null)
    }

    fun dispatchDoubleTap(x: Float, y: Float, callback: ((Boolean) -> Unit)? = null) {
        dispatchTap(x, y, 40) { success ->
            if (success) {
                android.os.Handler(android.os.Looper.getMainLooper()).postDelayed({
                    dispatchTap(x, y, 40, callback)
                }, 120)
            } else {
                callback?.invoke(false)
            }
        }
    }

    fun dispatchSwipe(
        startX: Float,
        startY: Float,
        endX: Float,
        endY: Float,
        durationMs: Long = 300,
        callback: ((Boolean) -> Unit)? = null
    ) {
        val path = Path().apply {
            moveTo(startX, startY)
            lineTo(endX, endY)
        }
        val stroke = GestureDescription.StrokeDescription(path, 0, durationMs.coerceAtLeast(50))
        val gesture = GestureDescription.Builder().addStroke(stroke).build()

        dispatchGesture(gesture, object : GestureResultCallback() {
            override fun onCompleted(gestureDescription: GestureDescription?) {
                Log.d(TAG, "Swipe completed: ($startX, $startY) -> ($endX, $endY)")
                callback?.invoke(true)
            }

            override fun onCancelled(gestureDescription: GestureDescription?) {
                Log.w(TAG, "Swipe cancelled: ($startX, $startY) -> ($endX, $endY)")
                callback?.invoke(false)
            }
        }, null)
    }

    // ==========================================
    // VIEW-TREE DUMP & NODE ACTIONS
    // ==========================================

    fun dumpViewTree(): Map<String, Any?> {
        val root = rootInActiveWindow ?: return mapOf(
            "package" to currentPackage,
            "error" to "rootInActiveWindow is null (screen locked or transition in progress)",
            "nodes" to emptyList<Map<String, Any?>>()
        )

        val nodeList = mutableListOf<Map<String, Any?>>()
        extractNodeRecursive(root, nodeList)

        return mapOf(
            "package" to currentPackage,
            "nodeCount" to nodeList.size,
            "nodes" to nodeList
        )
    }

    private fun extractNodeRecursive(node: AccessibilityNodeInfo?, list: MutableList<Map<String, Any?>>) {
        if (node == null) return

        val bounds = Rect()
        node.getBoundsInScreen(bounds)

        // Only record visible nodes or nodes with bounding areas
        if (bounds.width() > 0 && bounds.height() > 0) {
            val nodeMap = mutableMapOf<String, Any?>(
                "id" to node.viewIdResourceName,
                "className" to node.className?.toString(),
                "text" to node.text?.toString(),
                "contentDesc" to node.contentDescription?.toString(),
                "isClickable" to node.isClickable,
                "isEditable" to node.isEditable,
                "isSelected" to node.isSelected,
                "isChecked" to node.isChecked,
                "isEnabled" to node.isEnabled,
                "bounds" to mapOf(
                    "left" to bounds.left,
                    "top" to bounds.top,
                    "right" to bounds.right,
                    "bottom" to bounds.bottom,
                    "cx" to bounds.centerX(),
                    "cy" to bounds.centerY()
                )
            )
            list.add(nodeMap)
        }

        for (i in 0 until node.childCount) {
            val child = node.getChild(i)
            if (child != null) {
                extractNodeRecursive(child, list)
            }
        }
    }

    fun findAndClick(targetText: String? = null, resourceId: String? = null): Boolean {
        val root = rootInActiveWindow
        val matchingNodes = mutableListOf<AccessibilityNodeInfo>()

        if (root != null) {
            if (!resourceId.isNullOrBlank()) {
                matchingNodes.addAll(root.findAccessibilityNodeInfosByViewId(resourceId))
            }
            if (matchingNodes.isEmpty() && !targetText.isNullOrBlank()) {
                matchingNodes.addAll(root.findAccessibilityNodeInfosByText(targetText))
                if (matchingNodes.isEmpty()) {
                    findNodesByTextOrDesc(root, targetText, matchingNodes)
                }
            }
        }

        // Multi-window fallback (keyguard, IME windows, overlays)
        if (matchingNodes.isEmpty()) {
            try {
                val allWindows = windows
                if (allWindows != null) {
                    for (window in allWindows) {
                        val winRoot = window.root ?: continue
                        if (!resourceId.isNullOrBlank()) {
                            matchingNodes.addAll(winRoot.findAccessibilityNodeInfosByViewId(resourceId))
                        }
                        if (matchingNodes.isEmpty() && !targetText.isNullOrBlank()) {
                            matchingNodes.addAll(winRoot.findAccessibilityNodeInfosByText(targetText))
                            if (matchingNodes.isEmpty()) {
                                findNodesByTextOrDesc(winRoot, targetText, matchingNodes)
                            }
                        }
                        if (matchingNodes.isNotEmpty()) break
                    }
                }
            } catch (e: Exception) {
                Log.w(TAG, "Window traversal error in findAndClick: ${e.message}")
            }
        }

        for (node in matchingNodes) {
            var current: AccessibilityNodeInfo? = node
            while (current != null) {
                if (current.isClickable) {
                    val clicked = current.performAction(AccessibilityNodeInfo.ACTION_CLICK)
                    if (clicked) {
                        Log.d(TAG, "Successfully clicked target: $targetText / $resourceId")
                        return true
                    }
                }
                current = current.parent
            }

            // If not clickable directly via action, dispatch a coordinate tap to its center
            val bounds = Rect()
            node.getBoundsInScreen(bounds)
            if (bounds.width() > 0 && bounds.height() > 0) {
                dispatchTap(bounds.centerX().toFloat(), bounds.centerY().toFloat())
                return true
            }
        }

        return false
    }

    fun findAndSetText(targetHintOrId: String, textToType: String): Boolean {
        var targets: List<AccessibilityNodeInfo> = emptyList()
        val root = rootInActiveWindow

        // 1. Try finding by ID if query string is non-empty
        if (root != null && targetHintOrId.isNotBlank()) {
            targets = root.findAccessibilityNodeInfosByViewId(targetHintOrId)
            // 2. Try finding by text/hint
            if (targets.isEmpty()) {
                targets = root.findAccessibilityNodeInfosByText(targetHintOrId)
            }
        }

        // 3. Fallback: Find first editable node on active window root
        if (targets.isEmpty() && root != null) {
            targets = findFirstEditableNode(root)
        }

        // 4. Multi-window fallback: Lockscreen password field may reside in Keyguard / System window
        if (targets.isEmpty()) {
            try {
                val allWindows = windows
                if (allWindows != null) {
                    for (window in allWindows) {
                        val winRoot = window.root ?: continue
                        val found = findFirstEditableNode(winRoot)
                        if (found.isNotEmpty()) {
                            targets = found
                            break
                        }
                    }
                }
            } catch (e: Exception) {
                Log.w(TAG, "Error traversing windows for editable node: ${e.message}")
            }
        }

        for (node in targets) {
            if (node.isEditable || (node.className?.contains("EditText", ignoreCase = true) == true)) {
                node.performAction(AccessibilityNodeInfo.ACTION_CLICK)
                node.performAction(AccessibilityNodeInfo.ACTION_FOCUS)

                // Clear any leftover characters first so password isn't corrupted
                val clearArgs = Bundle().apply {
                    putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, "")
                }
                node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, clearArgs)

                val arguments = Bundle().apply {
                    putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, textToType)
                }
                val set = node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, arguments)
                if (set) {
                    Log.d(TAG, "Set text successfully: '$textToType'")
                    return true
                }
            }
        }

        return false
    }

    fun submitActiveField(): Boolean {
        val root = rootInActiveWindow

        // 1. Try finding editable node and triggering ACTION_IME_ENTER
        val editables = mutableListOf<AccessibilityNodeInfo>()
        if (root != null) {
            editables.addAll(findFirstEditableNode(root))
        }
        if (editables.isEmpty()) {
            try {
                val allWindows = windows
                if (allWindows != null) {
                    for (window in allWindows) {
                        val winRoot = window.root ?: continue
                        val found = findFirstEditableNode(winRoot)
                        if (found.isNotEmpty()) {
                            editables.addAll(found)
                            break
                        }
                    }
                }
            } catch (e: Exception) {
                Log.w(TAG, "Error finding editable node for submit: ${e.message}")
            }
        }

        for (node in editables) {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                val imeDone = node.performAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_IME_ENTER.id)
                if (imeDone) {
                    Log.i(TAG, "Submitted field via ACTION_IME_ENTER")
                    return true
                }
            }
        }

        // 2. Try standard keyboard action button IDs (GBoard, ColorOS, Realme, AOSP)
        val actionKeyIds = listOf(
            "key_pos_action",
            "key_pos_ime_action",
            "keyguard_password_view",
            "confirm_button",
            "lock_screen_enter",
            "btn_confirm"
        )
        for (id in actionKeyIds) {
            if (findAndClick(resourceId = id)) {
                Log.i(TAG, "Clicked submit button by ID: $id")
                return true
            }
        }

        // 3. Try standard labels / content descriptions
        val actionLabels = listOf("Enter", "Done", "OK", "Go", "Submit", "Unlock", "Confirm", "✓")
        for (label in actionLabels) {
            if (findAndClick(targetText = label)) {
                Log.i(TAG, "Clicked submit button by label: $label")
                return true
            }
        }

        // 4. Inspect Input Method Window specifically
        try {
            val allWindows = windows
            if (allWindows != null) {
                for (window in allWindows) {
                    if (window.type == AccessibilityWindowInfo.TYPE_INPUT_METHOD) {
                        val winRoot = window.root ?: continue
                        for (id in actionKeyIds) {
                            val nodes = winRoot.findAccessibilityNodeInfosByViewId(id)
                            for (n in nodes) {
                                if (n.isClickable) {
                                    n.performAction(AccessibilityNodeInfo.ACTION_CLICK)
                                    Log.i(TAG, "Clicked keyboard window action key by ID: $id")
                                    return true
                                }
                            }
                        }
                        for (label in actionLabels) {
                            val nodes = mutableListOf<AccessibilityNodeInfo>()
                            findNodesByTextOrDesc(winRoot, label, nodes)
                            for (n in nodes) {
                                if (n.isClickable || n.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
                                    Log.i(TAG, "Clicked keyboard window action key by label: $label")
                                    return true
                                }
                            }
                        }
                    }
                }
            }
        } catch (e: Exception) {
            Log.w(TAG, "Error inspecting IME window: ${e.message}")
        }

        return false
    }

    private fun findNodesByTextOrDesc(node: AccessibilityNodeInfo?, query: String, results: MutableList<AccessibilityNodeInfo>) {
        if (node == null) return
        val t = node.text?.toString()
        val d = node.contentDescription?.toString()
        if ((t != null && t.contains(query, ignoreCase = true)) || (d != null && d.contains(query, ignoreCase = true))) {
            results.add(node)
            return
        }
        for (i in 0 until node.childCount) {
            findNodesByTextOrDesc(node.getChild(i), query, results)
        }
    }

    private fun findFirstEditableNode(root: AccessibilityNodeInfo?): List<AccessibilityNodeInfo> {
        val result = mutableListOf<AccessibilityNodeInfo>()
        fun recurse(node: AccessibilityNodeInfo?) {
            if (node == null || result.isNotEmpty()) return
            if (node.isEditable || (node.className?.contains("EditText", ignoreCase = true) == true)) {
                result.add(node)
                return
            }
            for (i in 0 until node.childCount) {
                recurse(node.getChild(i))
            }
        }
        recurse(root)
        return result
    }

    // ==========================================
    // SYSTEM NAVIGATION & GLOBAL ACTIONS
    // ==========================================

    fun performGlobal(action: String): Boolean {
        return when (action.lowercase()) {
            "back" -> performGlobalAction(GLOBAL_ACTION_BACK)
            "home" -> performGlobalAction(GLOBAL_ACTION_HOME)
            "recents" -> performGlobalAction(GLOBAL_ACTION_RECENTS)
            "notifications" -> performGlobalAction(GLOBAL_ACTION_NOTIFICATIONS)
            "quick_settings" -> performGlobalAction(GLOBAL_ACTION_QUICK_SETTINGS)
            "lock" -> performGlobalAction(GLOBAL_ACTION_LOCK_SCREEN)
            "take_screenshot" -> performGlobalAction(GLOBAL_ACTION_TAKE_SCREENSHOT)
            "power_dialog" -> performGlobalAction(GLOBAL_ACTION_POWER_DIALOG)
            else -> false
        }
    }

    fun checkAndDismissKnownPopup(): Boolean {
        val root = rootInActiveWindow ?: return false
        val preferredButtons = listOf("While using the app", "Allow", "ALLOW", "Turn on", "Keep running", "OK")
        for (btn in preferredButtons) {
            val nodes = root.findAccessibilityNodeInfosByText(btn)
            for (node in nodes) {
                if (node.isClickable) {
                    val clicked = node.performAction(AccessibilityNodeInfo.ACTION_CLICK)
                    if (clicked) {
                        Log.i(TAG, "Auto-dismissed popup with '$btn'")
                        return true
                    }
                }
            }
        }
        return false
    }
}

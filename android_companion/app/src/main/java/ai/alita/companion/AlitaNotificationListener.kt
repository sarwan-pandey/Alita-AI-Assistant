package ai.alita.companion

import android.app.Notification
import android.app.RemoteInput
import android.content.Intent
import android.os.Bundle
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import android.util.Log

/**
 * AlitaNotificationListener
 * Intercepts incoming messages from messaging apps (WhatsApp, Telegram, Instagram, SMS)
 * and executes Zero-Screen background replies using native RemoteInput.
 */
class AlitaNotificationListener : NotificationListenerService() {

    companion object {
        private const val TAG = "AlitaNotifListener"
        var instance: AlitaNotificationListener? = null
            private set

        val isRunning: Boolean
            get() = instance != null

        val TARGET_PACKAGES = setOf(
            "com.whatsapp",
            "com.whatsapp.w4b",
            "org.telegram.messenger",
            "org.thunderdog.challegram",
            "com.instagram.android",
            "com.google.android.apps.messaging",
            "com.discord",
            "com.google.android.gm"
        )
    }

    override fun onListenerConnected() {
        super.onListenerConnected()
        instance = this
        Log.i(TAG, "Alita Notification Listener Connected")
        AlitaPhoneBridgeService.instance?.notifyStatus("NOTIF_CONNECTED")
    }

    override fun onListenerDisconnected() {
        super.onListenerDisconnected()
        if (instance == this) {
            instance = null
        }
        Log.w(TAG, "Alita Notification Listener Disconnected")
    }

    override fun onDestroy() {
        super.onDestroy()
        if (instance == this) {
            instance = null
        }
    }

    override fun onNotificationPosted(sbn: StatusBarNotification?) {
        if (sbn == null) return
        val pkg = sbn.packageName

        // Only process supported messaging/communication apps
        if (!TARGET_PACKAGES.contains(pkg)) return

        val notification = sbn.notification ?: return
        val extras = notification.extras ?: return

        val title = extras.getCharSequence(Notification.EXTRA_TITLE)?.toString() ?: ""
        val text = extras.getCharSequence(Notification.EXTRA_TEXT)?.toString() ?: ""

        // Ignore empty summaries
        if (title.isBlank() && text.isBlank()) return

        val hasReplyAction = findQuickReplyAction(notification) != null

        Log.d(TAG, "Notification from $pkg: '$title': '$text' [QuickReply: $hasReplyAction]")

        // Send event to Alita Desktop via Bridge
        val notifPayload = mapOf(
            "type" to "phone_notification",
            "key" to sbn.key,
            "package" to pkg,
            "title" to title,
            "text" to text,
            "timestamp" to sbn.postTime,
            "canReply" to hasReplyAction
        )

        AlitaPhoneBridgeService.instance?.broadcastEvent(notifPayload)
    }

    /**
     * Executes Zero-Screen instant reply without waking the display or opening the app
     */
    fun replyDirectly(notificationKey: String, replyText: String): Boolean {
        try {
            val notifications = activeNotifications ?: return false
            val targetSbn = notifications.firstOrNull { it.key == notificationKey }

            if (targetSbn == null) {
                Log.w(TAG, "Cannot find notification with key: $notificationKey")
                return false
            }

            val action = findQuickReplyAction(targetSbn.notification)
            if (action == null || action.remoteInputs == null) {
                Log.w(TAG, "No RemoteInput action found for notification: $notificationKey")
                return false
            }

            val intent = Intent()
            val bundle = Bundle()
            for (remoteInput in action.remoteInputs) {
                bundle.putCharSequence(remoteInput.resultKey, replyText)
            }
            RemoteInput.addResultsToIntent(action.remoteInputs, intent, bundle)
            action.actionIntent.send(this, 0, intent)

            Log.i(TAG, "Successfully dispatched direct reply to $notificationKey: '$replyText'")
            return true
        } catch (e: Exception) {
            Log.e(TAG, "Failed to reply directly: ${e.message}", e)
            return false
        }
    }

    private fun findQuickReplyAction(notification: Notification): Notification.Action? {
        val actions = notification.actions ?: return null
        for (action in actions) {
            val remoteInputs = action.remoteInputs
            if (remoteInputs != null && remoteInputs.isNotEmpty()) {
                return action
            }
        }
        return null
    }

    /**
     * Dismiss a specific notification by key
     */
    fun dismissNotification(key: String): Boolean {
        try {
            cancelNotification(key)
            Log.i(TAG, "Dismissed notification: $key")
            return true
        } catch (e: Exception) {
            Log.e(TAG, "Failed to dismiss notification: ${e.message}", e)
            return false
        }
    }

    /**
     * Clear all active notifications
     */
    fun clearAllNotifications(): Boolean {
        try {
            cancelAllNotifications()
            Log.i(TAG, "Cleared all active notifications")
            return true
        } catch (e: Exception) {
            Log.e(TAG, "Failed to clear all notifications: ${e.message}", e)
            return false
        }
    }

    /**
     * Retrieve current list of active notifications with metadata
     */
    fun getActiveNotificationsList(): List<Map<String, Any?>> {
        val notifs = activeNotifications ?: return emptyList()
        return notifs.map { sbn ->
            val extras = sbn.notification?.extras
            mapOf(
                "key" to sbn.key,
                "package" to sbn.packageName,
                "title" to (extras?.getCharSequence(Notification.EXTRA_TITLE)?.toString() ?: ""),
                "text" to (extras?.getCharSequence(Notification.EXTRA_TEXT)?.toString() ?: ""),
                "timestamp" to sbn.postTime,
                "canReply" to (sbn.notification?.let { findQuickReplyAction(it) != null } ?: false)
            )
        }
    }
}

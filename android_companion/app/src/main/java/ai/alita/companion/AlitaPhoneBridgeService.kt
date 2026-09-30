package ai.alita.companion

import android.app.KeyguardManager
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.bluetooth.BluetoothAdapter
import android.content.BroadcastReceiver
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.hardware.camera2.CameraManager
import android.media.AudioManager
import android.media.session.MediaController
import android.media.session.MediaSessionManager
import android.net.Uri
import android.net.wifi.WifiManager
import android.os.BatteryManager
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager
import android.os.VibrationEffect
import android.os.Vibrator
import android.provider.AlarmClock
import android.provider.ContactsContract
import android.provider.Settings
import android.telecom.TelecomManager
import android.telephony.SmsManager
import android.util.Log
import androidx.core.app.NotificationCompat
import com.google.gson.Gson
import com.google.gson.JsonObject
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import java.util.concurrent.TimeUnit

/**
 * AlitaPhoneBridgeService
 * Foreground service that maintains a real-time WebSocket connection to Alita PC.
 * Receives remote automation commands, dispatches them via Accessibility / Notification services,
 * and reports telemetry (battery, view tree, notifications) back to PC.
 */
class AlitaPhoneBridgeService : Service() {

    companion object {
        private const val TAG = "AlitaPhoneBridge"
        private const val CHANNEL_ID = "alita_bridge_channel"
        private const val NOTIFICATION_ID = 4041

        const val ACTION_START = "ai.alita.companion.START"
        const val ACTION_STOP = "ai.alita.companion.STOP"
        const val EXTRA_HOST = "extra_host"
        const val EXTRA_PORT = "extra_port"

        var instance: AlitaPhoneBridgeService? = null
            private set

        val isConnected: Boolean
            get() = instance?.webSocket != null
    }

    private val gson = Gson()
    private val mainHandler = Handler(Looper.getMainLooper())
    private var webSocket: WebSocket? = null
    private var okHttpClient: OkHttpClient? = null

    private var host: String = "192.168.1.100"
    private var port: Int = 8000
    private var isShouldReconnect: Boolean = true
    private var reconnectAttempts: Int = 0

    private val periodicTelemetryRunnable = object : Runnable {
        override fun run() {
            sendTelemetry()
            mainHandler.postDelayed(this, 10000) // Send telemetry every 10s
        }
    }

    private val screenStateReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            val action = intent?.action ?: return
            val km = getSystemService(Context.KEYGUARD_SERVICE) as? KeyguardManager
            val isLocked = km?.isKeyguardLocked ?: false

            when (action) {
                Intent.ACTION_SCREEN_ON -> {
                    notifyScreenState(isScreenOn = true, isLocked = isLocked)
                }
                Intent.ACTION_SCREEN_OFF -> {
                    notifyScreenState(isScreenOn = false, isLocked = true)
                }
                Intent.ACTION_USER_PRESENT -> {
                    notifyScreenState(isScreenOn = true, isLocked = false)
                }
            }
        }
    }

    override fun onCreate() {
        super.onCreate()
        instance = this
        createNotificationChannel()

        okHttpClient = OkHttpClient.Builder()
            .readTimeout(0, TimeUnit.MILLISECONDS)
            .pingInterval(15, TimeUnit.SECONDS)
            .build()

        val screenFilter = IntentFilter().apply {
            addAction(Intent.ACTION_SCREEN_ON)
            addAction(Intent.ACTION_SCREEN_OFF)
            addAction(Intent.ACTION_USER_PRESENT)
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            registerReceiver(screenStateReceiver, screenFilter, Context.RECEIVER_NOT_EXPORTED)
        } else {
            registerReceiver(screenStateReceiver, screenFilter)
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent == null) return START_STICKY

        when (intent.action) {
            ACTION_STOP -> {
                disconnect()
                stopForeground(true)
                stopSelf()
                return START_NOT_STICKY
            }
            ACTION_START -> {
                host = intent.getStringExtra(EXTRA_HOST) ?: host
                port = intent.getIntExtra(EXTRA_PORT, port)
                startForeground(NOTIFICATION_ID, buildForegroundNotification("Connecting to MJ PC..."))
                isShouldReconnect = true
                connect()
            }
        }

        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        super.onDestroy()
        isShouldReconnect = false
        disconnect()
        mainHandler.removeCallbacks(periodicTelemetryRunnable)
        try {
            unregisterReceiver(screenStateReceiver)
        } catch (e: Exception) {
            Log.w(TAG, "screenStateReceiver unregister notice: ${e.message}")
        }
        if (instance == this) {
            instance = null
        }
    }

    // ==========================================
    // WEBSOCKET LIFECYCLE & PROTOCOL
    // ==========================================

    @Synchronized
    fun connect() {
        disconnect()

        val trimmedHost = host.trim()
        val wsUrl = when {
            trimmedHost.startsWith("ws://") || trimmedHost.startsWith("wss://") -> {
                if (trimmedHost.endsWith("/ws/phone")) trimmedHost else "${trimmedHost.trimEnd('/')}/ws/phone"
            }
            trimmedHost.startsWith("https://") -> {
                val stripped = trimmedHost.removePrefix("https://").trimEnd('/')
                "wss://$stripped/ws/phone"
            }
            trimmedHost.startsWith("http://") -> {
                val stripped = trimmedHost.removePrefix("http://").trimEnd('/')
                "ws://$stripped/ws/phone"
            }
            trimmedHost.contains(".trycloudflare.com") || trimmedHost.contains(".cloudflare.com") ||
            trimmedHost.contains(".ngrok") || trimmedHost.contains(".dev") || port == 443 -> {
                val cleanHost = trimmedHost.trimEnd('/')
                "wss://$cleanHost/ws/phone"
            }
            else -> {
                "ws://$trimmedHost:$port/ws/phone"
            }
        }
        Log.i(TAG, "Connecting to MJ PC at: $wsUrl")

        val request = Request.Builder()
            .url(wsUrl)
            .addHeader("ngrok-skip-browser-warning", "69420")
            .build()

        webSocket = okHttpClient?.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                Log.i(TAG, "Connected to MJ PC!")
                reconnectAttempts = 0
                updateForegroundNotification("Connected to MJ PC ($host:$port)")
                
                // Send initial handshake
                sendHandshake()

                // Start telemetry loop
                mainHandler.post(periodicTelemetryRunnable)
                notifyActivityStatus("CONNECTED")
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                handleIncomingMessage(text)
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                Log.w(TAG, "Closing: $code / $reason")
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                Log.i(TAG, "WebSocket Closed")
                handleDisconnect()
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                Log.e(TAG, "WebSocket Failure: ${t.message}")
                handleDisconnect()
            }
        })
    }

    @Synchronized
    fun disconnect() {
        webSocket?.close(1000, "User requested disconnect")
        webSocket = null
        mainHandler.removeCallbacks(periodicTelemetryRunnable)
    }

    private fun handleDisconnect() {
        webSocket = null
        mainHandler.removeCallbacks(periodicTelemetryRunnable)
        updateForegroundNotification("Disconnected from MJ PC")
        notifyActivityStatus("OFFLINE")

        if (isShouldReconnect) {
            val delay = (1000L * (1 shl reconnectAttempts.coerceAtMost(5))).coerceAtMost(30000L)
            reconnectAttempts++
            Log.i(TAG, "Reconnecting in ${delay}ms (Attempt #$reconnectAttempts)...")
            mainHandler.postDelayed({
                if (isShouldReconnect && webSocket == null) {
                    connect()
                }
            }, delay)
        }
    }

    // ==========================================
    // INCOMING MESSAGE HANDLER
    // ==========================================

    private fun handleIncomingMessage(jsonText: String) {
        try {
            val json = gson.fromJson(jsonText, JsonObject::class.java)
            val command = json.get("command")?.asString ?: ""
            val commandId = json.get("id")?.asString ?: System.currentTimeMillis().toString()

            Log.d(TAG, "Executing command: '$command' (id: $commandId)")

            when (command) {
                "ping" -> {
                    val clientTime = json.get("timestamp")?.asLong ?: 0L
                    sendReply(mapOf(
                        "type" to "pong",
                        "id" to commandId,
                        "clientTimestamp" to clientTime,
                        "serverTimestamp" to System.currentTimeMillis()
                    ))
                }

                "tap" -> {
                    val x = json.get("x").asFloat
                    val y = json.get("y").asFloat
                    val duration = json.get("duration")?.asLong ?: 50L
                    AlitaAccessibilityService.instance?.dispatchTap(x, y, duration) { success ->
                        sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to success))
                    } ?: sendServiceError(commandId, "AccessibilityService not active")
                }

                "double_tap" -> {
                    val x = json.get("x").asFloat
                    val y = json.get("y").asFloat
                    AlitaAccessibilityService.instance?.dispatchDoubleTap(x, y) { success ->
                        sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to success))
                    } ?: sendServiceError(commandId, "AccessibilityService not active")
                }

                "swipe" -> {
                    val startX = json.get("startX").asFloat
                    val startY = json.get("startY").asFloat
                    val endX = json.get("endX").asFloat
                    val endY = json.get("endY").asFloat
                    val duration = json.get("duration")?.asLong ?: 300L
                    AlitaAccessibilityService.instance?.dispatchSwipe(startX, startY, endX, endY, duration) { success ->
                        sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to success))
                    } ?: sendServiceError(commandId, "AccessibilityService not active")
                }

                "type" -> {
                    val target = json.get("target")?.asString ?: ""
                    val text = json.get("text")?.asString ?: ""
                    val success = AlitaAccessibilityService.instance?.findAndSetText(target, text) ?: false
                    sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to success))
                }

                "click" -> {
                    val targetText = json.get("target")?.asString
                    val resourceId = json.get("resourceId")?.asString
                    val success = AlitaAccessibilityService.instance?.findAndClick(targetText, resourceId) ?: false
                    sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to success))
                }

                "global" -> {
                    val action = json.get("action")?.asString ?: ""
                    val success = AlitaAccessibilityService.instance?.performGlobal(action) ?: false
                    sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to success))
                }

                "dump_tree" -> {
                    val a11y = AlitaAccessibilityService.instance
                    if (a11y != null) {
                        val tree = a11y.dumpViewTree()
                        sendReply(mapOf("type" to "view_tree", "id" to commandId, "data" to tree))
                    } else {
                        sendServiceError(commandId, "AccessibilityService not active")
                    }
                }

                "direct_reply" -> {
                    val notifKey = json.get("notificationKey").asString
                    val replyText = json.get("text").asString
                    val success = AlitaNotificationListener.instance?.replyDirectly(notifKey, replyText) ?: false
                    sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to success))
                }

                "launch_app" -> {
                    val pkg = json.get("package")?.asString
                    val deepLink = json.get("deepLink")?.asString
                    var launched = false

                    // Ensure screen is awake so Android allows launching activity
                    val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
                    if (!pm.isInteractive) {
                        @Suppress("DEPRECATION")
                        val wakeLock = pm.newWakeLock(PowerManager.SCREEN_BRIGHT_WAKE_LOCK or PowerManager.ACQUIRE_CAUSES_WAKEUP, "alita:wake_launch")
                        wakeLock.acquire(3000)
                    }

                    if (!deepLink.isNullOrBlank()) {
                        try {
                            val intent = Intent(Intent.ACTION_VIEW, Uri.parse(deepLink)).apply {
                                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                            }
                            startActivity(intent)
                            launched = true
                        } catch (e: Exception) {
                            Log.e(TAG, "Failed deep link: $deepLink", e)
                        }
                    }

                    if (!launched && !pkg.isNullOrBlank()) {
                        val launchIntent = packageManager.getLaunchIntentForPackage(pkg)
                        if (launchIntent != null) {
                            launchIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                            startActivity(launchIntent)
                            launched = true
                        } else {
                            // Fallback implicit launcher intent if package visibility filtered
                            try {
                                val fallback = Intent(Intent.ACTION_MAIN).apply {
                                    addCategory(Intent.CATEGORY_LAUNCHER)
                                    setPackage(pkg)
                                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                                }
                                startActivity(fallback)
                                launched = true
                            } catch (e: Exception) {
                                Log.e(TAG, "Fallback launch intent failed for $pkg", e)
                            }
                        }
                    }

                    sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to launched))
                }

                "get_state" -> {
                    val km = getSystemService(Context.KEYGUARD_SERVICE) as? KeyguardManager
                    val pm = getSystemService(Context.POWER_SERVICE) as? PowerManager
                    val isInteractive = pm?.isInteractive ?: false
                    val isLocked = km?.isKeyguardLocked ?: false
                    val battery = getBatteryInfo()
                    val a11y = AlitaAccessibilityService.instance
                    val root = a11y?.rootInActiveWindow
                    val pkg = a11y?.currentPackage?.takeIf { it.isNotBlank() } ?: root?.packageName?.toString() ?: ""
                    val cls = root?.className?.toString() ?: ""
                    val hasOverlay = cls.contains("Dialog", ignoreCase = true) || cls.contains("Popup", ignoreCase = true)

                    sendReply(mapOf(
                        "type" to "command_result",
                        "id" to commandId,
                        "success" to true,
                        "isScreenOn" to isInteractive,
                        "isLocked" to isLocked,
                        "currentPackage" to pkg,
                        "batteryPercent" to battery.first,
                        "isCharging" to battery.second,
                        "hasOverlayPopup" to hasOverlay,
                        "deviceModel" to "${Build.MANUFACTURER} ${Build.MODEL}",
                        "androidVersion" to Build.VERSION.RELEASE
                    ))
                }

                "read_screen" -> {
                    val a11y = AlitaAccessibilityService.instance
                    if (a11y != null) {
                        val tree = a11y.dumpViewTree()
                        sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to true, "data" to tree))
                    } else {
                        sendServiceError(commandId, "AccessibilityService not active")
                    }
                }

                "unlock", "unlock_screen" -> {
                    val pin = json.get("pin")?.asString ?: getSavedUnlockCredential()
                    unlockDevice(pin, commandId)
                }

                // ==========================================
                // FULL PHONE AUTOMATION COMMANDS
                // ==========================================

                "make_call" -> {
                    val number = json.get("number")?.asString
                    val contactName = json.get("contactName")?.asString
                    var dialNumber = number

                    // Resolve contact name to phone number if needed
                    if (dialNumber.isNullOrBlank() && !contactName.isNullOrBlank()) {
                        dialNumber = resolveContactNumber(contactName)
                    }

                    if (!dialNumber.isNullOrBlank()) {
                        try {
                            val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
                            if (!pm.isInteractive) {
                                @Suppress("DEPRECATION")
                                val wakeLock = pm.newWakeLock(PowerManager.SCREEN_BRIGHT_WAKE_LOCK or PowerManager.ACQUIRE_CAUSES_WAKEUP, "alita:wake_call")
                                wakeLock.acquire(3000)
                            }
                            val callIntent = Intent(Intent.ACTION_CALL, Uri.parse("tel:$dialNumber")).apply {
                                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                            }
                            startActivity(callIntent)
                            sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to true, "number" to dialNumber))
                        } catch (e: SecurityException) {
                            sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to false, "error" to "CALL_PHONE permission not granted"))
                        } catch (e: Exception) {
                            sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to false, "error" to (e.message ?: "Call failed")))
                        }
                    } else {
                        sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to false, "error" to "No phone number or contact name provided"))
                    }
                }

                "end_call" -> {
                    try {
                        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                            val telecom = getSystemService(Context.TELECOM_SERVICE) as? TelecomManager
                            val ended = telecom?.endCall() ?: false
                            sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to ended))
                        } else {
                            sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to false, "error" to "Requires Android 9+"))
                        }
                    } catch (e: SecurityException) {
                        sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to false, "error" to "ANSWER_PHONE_CALLS permission not granted"))
                    }
                }

                "send_sms" -> {
                    val number = json.get("number")?.asString
                    val contactName = json.get("contactName")?.asString
                    val message = json.get("message")?.asString ?: ""
                    var smsNumber = number

                    if (smsNumber.isNullOrBlank() && !contactName.isNullOrBlank()) {
                        smsNumber = resolveContactNumber(contactName)
                    }

                    if (!smsNumber.isNullOrBlank() && message.isNotBlank()) {
                        try {
                            @Suppress("DEPRECATION")
                            val smsManager = SmsManager.getDefault()
                            smsManager.sendTextMessage(smsNumber, null, message, null, null)
                            sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to true, "number" to smsNumber))
                        } catch (e: Exception) {
                            sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to false, "error" to (e.message ?: "SMS failed")))
                        }
                    } else {
                        sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to false, "error" to "Missing number or message"))
                    }
                }

                "set_volume" -> {
                    val stream = when (json.get("stream")?.asString?.lowercase()) {
                        "media", "music" -> AudioManager.STREAM_MUSIC
                        "ring", "ringtone" -> AudioManager.STREAM_RING
                        "alarm" -> AudioManager.STREAM_ALARM
                        "notification", "notif" -> AudioManager.STREAM_NOTIFICATION
                        else -> AudioManager.STREAM_MUSIC
                    }
                    val audioManager = getSystemService(Context.AUDIO_SERVICE) as AudioManager
                    val maxVol = audioManager.getStreamMaxVolume(stream)
                    val action = json.get("action")?.asString?.lowercase()
                    val level = json.get("level")?.asInt

                    when (action) {
                        "up" -> audioManager.adjustStreamVolume(stream, AudioManager.ADJUST_RAISE, AudioManager.FLAG_SHOW_UI)
                        "down" -> audioManager.adjustStreamVolume(stream, AudioManager.ADJUST_LOWER, AudioManager.FLAG_SHOW_UI)
                        "mute" -> audioManager.adjustStreamVolume(stream, AudioManager.ADJUST_MUTE, 0)
                        "unmute" -> audioManager.adjustStreamVolume(stream, AudioManager.ADJUST_UNMUTE, 0)
                        "max" -> audioManager.setStreamVolume(stream, maxVol, AudioManager.FLAG_SHOW_UI)
                        "min" -> audioManager.setStreamVolume(stream, 0, AudioManager.FLAG_SHOW_UI)
                        else -> {
                            if (level != null) {
                                val actualLevel = (level * maxVol / 100).coerceIn(0, maxVol)
                                audioManager.setStreamVolume(stream, actualLevel, AudioManager.FLAG_SHOW_UI)
                            }
                        }
                    }
                    val currentVol = audioManager.getStreamVolume(stream)
                    sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to true, "currentVolume" to currentVol, "maxVolume" to maxVol))
                }

                "media_control" -> {
                    val action = json.get("action")?.asString?.lowercase() ?: "play_pause"
                    val audioManager = getSystemService(Context.AUDIO_SERVICE) as AudioManager
                    val keyCode = when (action) {
                        "play", "resume" -> android.view.KeyEvent.KEYCODE_MEDIA_PLAY
                        "pause" -> android.view.KeyEvent.KEYCODE_MEDIA_PAUSE
                        "play_pause", "toggle" -> android.view.KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE
                        "next", "skip" -> android.view.KeyEvent.KEYCODE_MEDIA_NEXT
                        "previous", "prev" -> android.view.KeyEvent.KEYCODE_MEDIA_PREVIOUS
                        "stop" -> android.view.KeyEvent.KEYCODE_MEDIA_STOP
                        else -> android.view.KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE
                    }
                    val downEvent = android.view.KeyEvent(android.view.KeyEvent.ACTION_DOWN, keyCode)
                    val upEvent = android.view.KeyEvent(android.view.KeyEvent.ACTION_UP, keyCode)
                    audioManager.dispatchMediaKeyEvent(downEvent)
                    audioManager.dispatchMediaKeyEvent(upEvent)
                    sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to true, "action" to action))
                }

                "toggle_flashlight" -> {
                    val enable = json.get("enabled")?.asBoolean ?: true
                    try {
                        val cameraManager = getSystemService(Context.CAMERA_SERVICE) as CameraManager
                        val cameraId = cameraManager.cameraIdList.firstOrNull() ?: ""
                        if (cameraId.isNotBlank()) {
                            cameraManager.setTorchMode(cameraId, enable)
                            sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to true, "flashlightOn" to enable))
                        } else {
                            sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to false, "error" to "No camera found"))
                        }
                    } catch (e: Exception) {
                        sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to false, "error" to (e.message ?: "Flashlight error")))
                    }
                }

                "set_alarm" -> {
                    val hour = json.get("hour")?.asInt ?: 6
                    val minute = json.get("minute")?.asInt ?: 0
                    val label = json.get("label")?.asString ?: "MJ Alarm"
                    try {
                        val intent = Intent(AlarmClock.ACTION_SET_ALARM).apply {
                            putExtra(AlarmClock.EXTRA_HOUR, hour)
                            putExtra(AlarmClock.EXTRA_MINUTES, minute)
                            putExtra(AlarmClock.EXTRA_MESSAGE, label)
                            putExtra(AlarmClock.EXTRA_SKIP_UI, true)
                            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                        }
                        startActivity(intent)
                        sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to true, "hour" to hour, "minute" to minute))
                    } catch (e: Exception) {
                        sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to false, "error" to (e.message ?: "Alarm failed")))
                    }
                }

                "set_timer" -> {
                    val seconds = json.get("seconds")?.asInt ?: 60
                    val label = json.get("label")?.asString ?: "MJ Timer"
                    try {
                        val intent = Intent(AlarmClock.ACTION_SET_TIMER).apply {
                            putExtra(AlarmClock.EXTRA_LENGTH, seconds)
                            putExtra(AlarmClock.EXTRA_MESSAGE, label)
                            putExtra(AlarmClock.EXTRA_SKIP_UI, true)
                            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                        }
                        startActivity(intent)
                        sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to true, "seconds" to seconds))
                    } catch (e: Exception) {
                        sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to false, "error" to (e.message ?: "Timer failed")))
                    }
                }

                "set_clipboard" -> {
                    val text = json.get("text")?.asString ?: ""
                    mainHandler.post {
                        val clipManager = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                        clipManager.setPrimaryClip(ClipData.newPlainText("alita_clipboard", text))
                        sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to true))
                    }
                }

                "get_clipboard" -> {
                    mainHandler.post {
                        val clipManager = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                        val clipText = clipManager.primaryClip?.getItemAt(0)?.text?.toString() ?: ""
                        sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to true, "text" to clipText))
                    }
                }

                "open_camera" -> {
                    val selfie = json.get("selfie")?.asBoolean ?: false
                    try {
                        val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
                        if (!pm.isInteractive) {
                            @Suppress("DEPRECATION")
                            val wakeLock = pm.newWakeLock(PowerManager.SCREEN_BRIGHT_WAKE_LOCK or PowerManager.ACQUIRE_CAUSES_WAKEUP, "alita:wake_camera")
                            wakeLock.acquire(3000)
                        }
                        val cameraIntent = if (selfie) {
                            Intent("android.media.action.STILL_IMAGE_CAMERA_SECURE").apply {
                                putExtra("android.intent.extras.CAMERA_FACING", 1) // Front camera
                                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                            }
                        } else {
                            Intent("android.media.action.STILL_IMAGE_CAMERA").apply {
                                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                            }
                        }
                        startActivity(cameraIntent)
                        sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to true, "selfie" to selfie))
                    } catch (e: Exception) {
                        sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to false, "error" to (e.message ?: "Camera failed")))
                    }
                }

                "set_brightness" -> {
                    val level = json.get("level")?.asInt ?: 128  // 0-255
                    try {
                        val cr = contentResolver
                        // Disable auto-brightness first
                        Settings.System.putInt(cr, Settings.System.SCREEN_BRIGHTNESS_MODE, Settings.System.SCREEN_BRIGHTNESS_MODE_MANUAL)
                        Settings.System.putInt(cr, Settings.System.SCREEN_BRIGHTNESS, level.coerceIn(0, 255))
                        sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to true, "brightness" to level))
                    } catch (e: SecurityException) {
                        sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to false, "error" to "WRITE_SETTINGS permission required"))
                    } catch (e: Exception) {
                        sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to false, "error" to (e.message ?: "Brightness failed")))
                    }
                }

                "toggle_wifi" -> {
                    val enable = if (json.has("enabled")) json.get("enabled").asBoolean else null
                    try {
                        val wm = applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
                        val preState = wm.isWifiEnabled
                        val targetState = enable ?: !preState
                        var toggled = false
                        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) {
                            @Suppress("DEPRECATION")
                            toggled = wm.setWifiEnabled(targetState)
                        }
                        if (!toggled) {
                            // Fallback to Settings panel on Android 10+
                            val panelIntent = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                                Intent(Settings.Panel.ACTION_WIFI).apply { addFlags(Intent.FLAG_ACTIVITY_NEW_TASK) }
                            } else {
                                Intent(Settings.ACTION_WIFI_SETTINGS).apply { addFlags(Intent.FLAG_ACTIVITY_NEW_TASK) }
                            }
                            startActivity(panelIntent)
                            toggled = true
                        }
                        val postState = wm.isWifiEnabled
                        sendReply(mapOf(
                            "type" to "command_result",
                            "id" to commandId,
                            "success" to toggled,
                            "preState" to preState,
                            "wifiEnabled" to postState,
                            "targetState" to targetState
                        ))
                    } catch (e: Exception) {
                        sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to false, "error" to (e.message ?: "WiFi toggle failed")))
                    }
                }

                "toggle_bluetooth" -> {
                    val enable = if (json.has("enabled")) json.get("enabled").asBoolean else null
                    try {
                        @Suppress("DEPRECATION")
                        val ba = BluetoothAdapter.getDefaultAdapter()
                        if (ba == null) {
                            sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to false, "error" to "No Bluetooth adapter"))
                        } else {
                            val preState = ba.isEnabled
                            val targetState = enable ?: !preState
                            var toggled = false
                            if (targetState) {
                                @Suppress("DEPRECATION")
                                toggled = ba.enable()
                            } else {
                                @Suppress("DEPRECATION")
                                toggled = ba.disable()
                            }
                            if (!toggled) {
                                val intent = Intent(Settings.ACTION_BLUETOOTH_SETTINGS).apply { addFlags(Intent.FLAG_ACTIVITY_NEW_TASK) }
                                startActivity(intent)
                                toggled = true
                            }
                            sendReply(mapOf(
                                "type" to "command_result",
                                "id" to commandId,
                                "success" to toggled,
                                "preState" to preState,
                                "bluetoothEnabled" to ba.isEnabled,
                                "targetState" to targetState
                            ))
                        }
                    } catch (e: Exception) {
                        sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to false, "error" to (e.message ?: "Bluetooth toggle failed")))
                    }
                }

                "toggle_mobile_data" -> {
                    try {
                        val panelIntent = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                            Intent(Settings.Panel.ACTION_INTERNET_CONNECTIVITY).apply { addFlags(Intent.FLAG_ACTIVITY_NEW_TASK) }
                        } else {
                            Intent(Settings.ACTION_DATA_ROAMING_SETTINGS).apply { addFlags(Intent.FLAG_ACTIVITY_NEW_TASK) }
                        }
                        startActivity(panelIntent)
                        sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to true, "message" to "Opened network settings panel"))
                    } catch (e: Exception) {
                        sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to false, "error" to (e.message ?: "Mobile data panel failed")))
                    }
                }

                "toggle_airplane" -> {
                    try {
                        val isAirplaneOn = Settings.Global.getInt(contentResolver, Settings.Global.AIRPLANE_MODE_ON, 0) != 0
                        val intent = Intent(Settings.ACTION_AIRPLANE_MODE_SETTINGS).apply { addFlags(Intent.FLAG_ACTIVITY_NEW_TASK) }
                        startActivity(intent)
                        sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to true, "airplaneModeOn" to isAirplaneOn, "message" to "Opened airplane mode settings"))
                    } catch (e: Exception) {
                        sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to false, "error" to (e.message ?: "Airplane mode failed")))
                    }
                }

                "toggle_dnd" -> {
                    val enable = if (json.has("enabled")) json.get("enabled").asBoolean else true
                    try {
                        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
                        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                            if (!nm.isNotificationPolicyAccessGranted) {
                                val intent = Intent(Settings.ACTION_NOTIFICATION_POLICY_ACCESS_SETTINGS).apply { addFlags(Intent.FLAG_ACTIVITY_NEW_TASK) }
                                startActivity(intent)
                                sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to false, "error" to "DND permission not granted. Opened settings."))
                            } else {
                                val targetFilter = if (enable) NotificationManager.INTERRUPTION_FILTER_PRIORITY else NotificationManager.INTERRUPTION_FILTER_ALL
                                nm.setInterruptionFilter(targetFilter)
                                sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to true, "dndEnabled" to enable))
                            }
                        } else {
                            sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to false, "error" to "Requires Android 6+"))
                        }
                    } catch (e: Exception) {
                        sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to false, "error" to (e.message ?: "DND toggle failed")))
                    }
                }

                "toggle_auto_rotate" -> {
                    try {
                        val cr = contentResolver
                        val curr = Settings.System.getInt(cr, Settings.System.ACCELEROMETER_ROTATION, 0)
                        val target = if (json.has("enabled")) (if (json.get("enabled").asBoolean) 1 else 0) else (if (curr == 1) 0 else 1)
                        Settings.System.putInt(cr, Settings.System.ACCELEROMETER_ROTATION, target)
                        sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to true, "autoRotate" to (target == 1)))
                    } catch (e: SecurityException) {
                        sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to false, "error" to "WRITE_SETTINGS permission required"))
                    } catch (e: Exception) {
                        sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to false, "error" to (e.message ?: "Auto-rotate failed")))
                    }
                }

                "toggle_hotspot" -> {
                    try {
                        val intent = Intent().apply {
                            setClassName("com.android.settings", "com.android.settings.TetherSettings")
                            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                        }
                        try {
                            startActivity(intent)
                        } catch (_: Exception) {
                            val fallback = Intent("android.settings.TETHER_SETTINGS").apply { addFlags(Intent.FLAG_ACTIVITY_NEW_TASK) }
                            startActivity(fallback)
                        }
                        sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to true, "message" to "Opened hotspot settings"))
                    } catch (e: Exception) {
                        sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to false, "error" to (e.message ?: "Hotspot failed")))
                    }
                }

                "capture_photo" -> {
                    val selfie = json.get("selfie")?.asBoolean ?: false
                    try {
                        val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
                        if (!pm.isInteractive) {
                            @Suppress("DEPRECATION")
                            val wakeLock = pm.newWakeLock(PowerManager.SCREEN_BRIGHT_WAKE_LOCK or PowerManager.ACQUIRE_CAUSES_WAKEUP, "alita:wake_photo")
                            wakeLock.acquire(4000)
                        }
                        val a11y = AlitaAccessibilityService.instance
                        val currPkg = a11y?.currentPackage ?: ""
                        val isCameraOpen = currPkg.contains("camera", ignoreCase = true)

                        fun performShutterClick() {
                            val service = AlitaAccessibilityService.instance
                            if (service == null) {
                                sendServiceError(commandId, "AccessibilityService not active")
                                return
                            }
                            val clicked = service.findAndClick("Shutter") ||
                                          service.findAndClick("Take picture") ||
                                          service.findAndClick("Capture") ||
                                          service.findAndClick(targetText = null, resourceId = "shutter_button") ||
                                          service.findAndClick(targetText = null, resourceId = "btn_camera")

                            if (clicked) {
                                sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to true, "message" to "Photo captured via shutter button"))
                            } else {
                                val dm = resources.displayMetrics
                                val cx = dm.widthPixels * 0.5f
                                val cy = dm.heightPixels * 0.88f
                                service.dispatchTap(cx, cy, 50L) { tapSuccess ->
                                    sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to tapSuccess, "message" to "Photo captured via positional tap"))
                                }
                            }
                        }

                        if (!isCameraOpen) {
                            val cameraIntent = if (selfie) {
                                Intent("android.media.action.STILL_IMAGE_CAMERA_SECURE").apply {
                                    putExtra("android.intent.extras.CAMERA_FACING", 1)
                                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                                }
                            } else {
                                Intent("android.media.action.STILL_IMAGE_CAMERA").apply {
                                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                                }
                            }
                            startActivity(cameraIntent)
                            mainHandler.postDelayed({ performShutterClick() }, 1200)
                        } else {
                            performShutterClick()
                        }
                    } catch (e: Exception) {
                        sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to false, "error" to (e.message ?: "Capture photo failed")))
                    }
                }

                "answer_call" -> {
                    try {
                        var answered = false
                        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                            val telecom = getSystemService(Context.TELECOM_SERVICE) as? TelecomManager
                            try {
                                telecom?.acceptRingingCall()
                                answered = true
                            } catch (se: SecurityException) {
                                Log.w(TAG, "acceptRingingCall security exception: ${se.message}")
                            }
                        }
                        if (!answered) {
                            val a11y = AlitaAccessibilityService.instance
                            answered = (a11y?.findAndClick("Answer") ?: false) ||
                                       (a11y?.findAndClick("Accept") ?: false) ||
                                       (a11y?.findAndClick(targetText = null, resourceId = "answer_button") ?: false)
                        }
                        sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to answered))
                    } catch (e: Exception) {
                        sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to false, "error" to (e.message ?: "Answer call failed")))
                    }
                }

                "reject_call" -> {
                    try {
                        var rejected = false
                        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                            val telecom = getSystemService(Context.TELECOM_SERVICE) as? TelecomManager
                            try {
                                rejected = telecom?.endCall() ?: false
                            } catch (se: SecurityException) {
                                Log.w(TAG, "endCall security exception: ${se.message}")
                            }
                        }
                        if (!rejected) {
                            val a11y = AlitaAccessibilityService.instance
                            rejected = (a11y?.findAndClick("Decline") ?: false) ||
                                       (a11y?.findAndClick("Reject") ?: false) ||
                                       (a11y?.findAndClick(targetText = null, resourceId = "decline_button") ?: false)
                        }
                        sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to rejected))
                    } catch (e: Exception) {
                        sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to false, "error" to (e.message ?: "Reject call failed")))
                    }
                }

                "toggle_speaker" -> {
                    val enable = json.get("enabled")?.asBoolean ?: true
                    try {
                        val am = getSystemService(Context.AUDIO_SERVICE) as AudioManager
                        am.isSpeakerphoneOn = enable
                        sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to true, "speakerOn" to am.isSpeakerphoneOn))
                    } catch (e: Exception) {
                        sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to false, "error" to (e.message ?: "Speakerphone failed")))
                    }
                }

                "open_url" -> {
                    val urlStr = json.get("url")?.asString ?: ""
                    if (urlStr.isNotBlank()) {
                        try {
                            val isCustomScheme = urlStr.contains("://")
                            val fullUrl = if (!isCustomScheme && !urlStr.startsWith("http://") && !urlStr.startsWith("https://")) "https://$urlStr" else urlStr
                            val browserIntent = Intent(Intent.ACTION_VIEW, Uri.parse(fullUrl)).apply {
                                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                            }
                            startActivity(browserIntent)
                            sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to true, "url" to fullUrl))
                        } catch (e: Exception) {
                            sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to false, "error" to (e.message ?: "Open URL failed")))
                        }
                    } else {
                        sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to false, "error" to "No URL provided"))
                    }
                }

                "pay_upi" -> {
                    val recipient = json.get("recipient")?.asString ?: ""
                    val amount = if (json.has("amount")) json.get("amount").asDouble else 0.0
                    val vpa = json.get("vpa")?.asString
                    val appPackage = json.get("package")?.asString
                    val upiUri = json.get("upi_uri")?.asString

                    try {
                        val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
                        if (!pm.isInteractive) {
                            @Suppress("DEPRECATION")
                            val wakeLock = pm.newWakeLock(PowerManager.SCREEN_BRIGHT_WAKE_LOCK or PowerManager.ACQUIRE_CAUSES_WAKEUP, "alita:wake_upi")
                            wakeLock.acquire(4000)
                        }

                        val targetUriStr = if (!upiUri.isNullOrBlank()) {
                            upiUri
                        } else {
                            val encodedPn = Uri.encode(recipient)
                            val amtFormatted = String.format(java.util.Locale.US, "%.2f", amount)
                            if (!vpa.isNullOrBlank()) {
                                "upi://pay?pa=$vpa&pn=$encodedPn&am=$amtFormatted&cu=INR&tn=Payment"
                            } else {
                                "upi://pay?pn=$encodedPn&am=$amtFormatted&cu=INR&tn=Payment"
                            }
                        }

                        val intent = Intent(Intent.ACTION_VIEW, Uri.parse(targetUriStr)).apply {
                            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                            if (!appPackage.isNullOrBlank()) {
                                setPackage(appPackage)
                            }
                        }
                        startActivity(intent)
                        sendReply(mapOf(
                            "type" to "command_result",
                            "id" to commandId,
                            "success" to true,
                            "recipient" to recipient,
                            "amount" to amount,
                            "uri" to targetUriStr
                        ))
                    } catch (e: Exception) {
                        sendReply(mapOf(
                            "type" to "command_result",
                            "id" to commandId,
                            "success" to false,
                            "error" to (e.message ?: "UPI payment launch failed")
                        ))
                    }
                }

                "dismiss_notification" -> {
                    val key = json.get("key")?.asString ?: ""
                    val success = AlitaNotificationListener.instance?.dismissNotification(key) ?: false
                    sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to success, "key" to key))
                }

                "clear_all_notifications" -> {
                    val success = AlitaNotificationListener.instance?.clearAllNotifications() ?: false
                    sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to success))
                }

                "get_notifications" -> {
                    val list = AlitaNotificationListener.instance?.getActiveNotificationsList() ?: emptyList()
                    sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to true, "notifications" to list))
                }

                "vibrate" -> {
                    val durationMs = json.get("duration")?.asLong ?: 500L
                    try {
                        @Suppress("DEPRECATION")
                        val vibrator = getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator
                        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                            vibrator?.vibrate(VibrationEffect.createOneShot(durationMs, VibrationEffect.DEFAULT_AMPLITUDE))
                        } else {
                            @Suppress("DEPRECATION")
                            vibrator?.vibrate(durationMs)
                        }
                        sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to true, "duration" to durationMs))
                    } catch (e: Exception) {
                        sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to false, "error" to (e.message ?: "Vibrate failed")))
                    }
                }

                "set_ringer_mode" -> {
                    val mode = json.get("mode")?.asString?.lowercase() ?: "normal"
                    try {
                        val am = getSystemService(Context.AUDIO_SERVICE) as AudioManager
                        val ringerMode = when (mode) {
                            "silent" -> AudioManager.RINGER_MODE_SILENT
                            "vibrate" -> AudioManager.RINGER_MODE_VIBRATE
                            else -> AudioManager.RINGER_MODE_NORMAL
                        }
                        am.ringerMode = ringerMode
                        sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to true, "mode" to mode))
                    } catch (e: Exception) {
                        sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to false, "error" to (e.message ?: "Set ringer mode failed")))
                    }
                }

                else -> {
                    Log.w(TAG, "Unknown command received: $command")
                    sendReply(mapOf("type" to "error", "id" to commandId, "message" to "Unknown command: $command"))
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Error handling message: ${e.message}", e)
        }
    }

    private fun unlockDevice(passwordOrPin: String?, commandId: String) {
        val km = getSystemService(Context.KEYGUARD_SERVICE) as? KeyguardManager
        val pm = getSystemService(Context.POWER_SERVICE) as PowerManager

        // Check if device is already unlocked
        if (km != null && !km.isKeyguardLocked) {
            Log.i(TAG, "Device is already unlocked")
            if (!pm.isInteractive) {
                @Suppress("DEPRECATION")
                val wakeLock = pm.newWakeLock(PowerManager.SCREEN_BRIGHT_WAKE_LOCK or PowerManager.ACQUIRE_CAUSES_WAKEUP, "alita:wake_unlocked")
                wakeLock.acquire(3000)
            }
            val a11y = AlitaAccessibilityService.instance
            val root = a11y?.rootInActiveWindow
            val pkg = a11y?.currentPackage?.takeIf { it.isNotBlank() } ?: root?.packageName?.toString() ?: ""
            sendReply(mapOf(
                "type" to "command_result",
                "id" to commandId,
                "success" to true,
                "isLocked" to false,
                "alreadyUnlocked" to true,
                "currentPackage" to pkg,
                "message" to "Device is already unlocked"
            ))
            return
        }

        @Suppress("DEPRECATION")
        val wakeLock = pm.newWakeLock(PowerManager.SCREEN_BRIGHT_WAKE_LOCK or PowerManager.ACQUIRE_CAUSES_WAKEUP, "alita:wake")
        wakeLock.acquire(4000)

        // Give screen 400ms to wake, then swipe up from bottom to reveal password field / keypad
        mainHandler.postDelayed({
            val dm = resources.displayMetrics
            val cx = dm.widthPixels / 2f
            val startY = dm.heightPixels * 0.85f
            val endY = dm.heightPixels * 0.20f

            AlitaAccessibilityService.instance?.dispatchSwipe(cx, startY, cx, endY, 350) { swipeSuccess ->
                val secretToEnter = if (!passwordOrPin.isNullOrBlank()) passwordOrPin else (getSavedUnlockCredential() ?: "Abhi2003@")
                mainHandler.postDelayed({
                    enterPasswordOrPin(secretToEnter, commandId)
                }, 450)
            }
        }, 400)
    }

    private fun enterPasswordOrPin(secret: String, commandId: String) {
        val a11y = AlitaAccessibilityService.instance
        if (a11y == null) {
            sendReply(mapOf("type" to "command_result", "id" to commandId, "success" to false, "error" to "AccessibilityService not active"))
            return
        }

        val isAlphanumeric = secret.any { it.isLetter() || !it.isLetterOrDigit() }
        if (isAlphanumeric) {
            // Focus and enter full alphanumeric password into lockscreen EditText
            var setOk = a11y.findAndSetText("", secret)
            if (!setOk) {
                // Retry after 350ms in case lockscreen animation is still settling
                mainHandler.postDelayed({
                    a11y.findAndSetText("", secret)
                    submitPassword(commandId)
                }, 350)
            } else {
                mainHandler.postDelayed({
                    submitPassword(commandId)
                }, 250)
            }
        } else {
            // Numeric PIN: try set text directly, fallback to sequential keypad clicks
            val setOk = a11y.findAndSetText("", secret)
            if (setOk) {
                mainHandler.postDelayed({
                    submitPassword(commandId)
                }, 250)
            } else {
                enterPinDigits(secret, 0, commandId)
            }
        }
    }

    private fun submitPassword(commandId: String) {
        val a11y = AlitaAccessibilityService.instance
        if (a11y != null) {
            // Priority 1: Direct IME action / accessibility node submit (handles Android 11+ ACTION_IME_ENTER, IME window action keys, labels)
            val submitted = a11y.submitActiveField()

            if (!submitted) {
                // Priority 2: Standard UI button labels / checkmarks
                val clicked = a11y.findAndClick(targetText = "Enter") ||
                              a11y.findAndClick(targetText = "Done") ||
                              a11y.findAndClick(targetText = "OK") ||
                              a11y.findAndClick(targetText = "✓") ||
                              a11y.findAndClick(targetText = "Go")

                if (!clicked) {
                    // Priority 3: Calibrated bottom-right keyboard Enter button location.
                    // On modern 20:9 / tall aspect ratio displays (e.g. Realme RMX5030 with gesture navigation),
                    // row 4/5 action/Enter key sits at bottom right: x=92%, y=96.5%.
                    // (Note: y=0.92f lands on row 2 right-edge, tapping 'l' instead!)
                    val dm = resources.displayMetrics
                    a11y.dispatchTap(dm.widthPixels * 0.92f, dm.heightPixels * 0.965f)
                }
            }
        }
        pollKeyguardDismissal(commandId, System.currentTimeMillis())
    }

    private fun enterPinDigits(pin: String, index: Int, commandId: String) {
        if (index >= pin.length) {
            // All digits entered; submit PIN using the same high-reliability ladder
            submitPassword(commandId)
            return
        }

        val digit = pin[index].toString()
        AlitaAccessibilityService.instance?.findAndClick(digit)

        mainHandler.postDelayed({
            enterPinDigits(pin, index + 1, commandId)
        }, 150)
    }

    private fun pollKeyguardDismissal(commandId: String, startTime: Long) {
        val km = getSystemService(Context.KEYGUARD_SERVICE) as? KeyguardManager
        val isLocked = km?.isKeyguardLocked ?: false
        if (!isLocked) {
            val root = AlitaAccessibilityService.instance?.rootInActiveWindow
            val pkg = root?.packageName?.toString() ?: ""
            sendReply(mapOf(
                "type" to "command_result",
                "id" to commandId,
                "success" to true,
                "isLocked" to false,
                "verifiedUnlocked" to true,
                "currentPackage" to pkg
            ))
            return
        }

        if (System.currentTimeMillis() - startTime >= 3000L) {
            // Timeout - Keyguard still locked
            sendReply(mapOf(
                "type" to "command_result",
                "id" to commandId,
                "success" to false,
                "isLocked" to true,
                "verifiedUnlocked" to false,
                "error" to "Keyguard still active after credential entry"
            ))
            return
        }

        mainHandler.postDelayed({
            pollKeyguardDismissal(commandId, startTime)
        }, 150)
    }

    fun getSavedUnlockCredential(): String? {
        val prefs = getSharedPreferences("alita_secure_vault", Context.MODE_PRIVATE)
        return prefs.getString("device_unlock_secret", null)
    }

    fun saveUnlockCredential(credential: String) {
        val prefs = getSharedPreferences("alita_secure_vault", Context.MODE_PRIVATE)
        prefs.edit().putString("device_unlock_secret", credential).apply()
    }

    /**
     * Resolve a contact display name to a phone number using ContactsContract.
     * Returns the first matching phone number, or null if not found.
     */
    private fun resolveContactNumber(contactName: String): String? {
        try {
            val projection = arrayOf(
                ContactsContract.CommonDataKinds.Phone.NUMBER,
                ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME
            )
            val selection = "${ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME} LIKE ?"
            val selectionArgs = arrayOf("%$contactName%")

            val cursor = contentResolver.query(
                ContactsContract.CommonDataKinds.Phone.CONTENT_URI,
                projection,
                selection,
                selectionArgs,
                null
            )

            cursor?.use {
                if (it.moveToFirst()) {
                    val numberIndex = it.getColumnIndex(ContactsContract.CommonDataKinds.Phone.NUMBER)
                    if (numberIndex >= 0) {
                        val number = it.getString(numberIndex)
                        Log.i(TAG, "Resolved contact '$contactName' → $number")
                        return number
                    }
                }
            }
        } catch (e: SecurityException) {
            Log.w(TAG, "READ_CONTACTS permission not granted: ${e.message}")
        } catch (e: Exception) {
            Log.e(TAG, "Error resolving contact '$contactName': ${e.message}")
        }
        return null
    }

    // ==========================================
    // OUTGOING TELEMETRY & EVENTS
    // ==========================================

    fun broadcastEvent(payload: Map<String, Any?>) {
        sendReply(payload)
    }

    fun notifyStatus(status: String) {
        sendReply(mapOf("type" to "status_event", "status" to status))
    }

    fun notifyAppSwitched(pkg: String) {
        val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
        sendReply(mapOf(
            "type" to "app_switched",
            "package" to pkg,
            "isScreenOn" to pm.isInteractive,
            "timestamp" to System.currentTimeMillis()
        ))
        Log.d(TAG, "Instant app switch sent: $pkg")
    }

    fun notifyScreenState(isScreenOn: Boolean, isLocked: Boolean) {
        sendReply(mapOf(
            "type" to "screen_state",
            "isScreenOn" to isScreenOn,
            "isLocked" to isLocked,
            "timestamp" to System.currentTimeMillis()
        ))
        Log.d(TAG, "Instant screen state sent: on=$isScreenOn, locked=$isLocked")
    }

    private fun sendHandshake() {
        val battery = getBatteryInfo()
        val payload = mapOf(
            "type" to "handshake",
            "deviceModel" to "${Build.MANUFACTURER} ${Build.MODEL}",
            "androidVersion" to Build.VERSION.RELEASE,
            "sdkVersion" to Build.VERSION.SDK_INT,
            "accessibilityActive" to AlitaAccessibilityService.isRunning,
            "notificationListenerActive" to AlitaNotificationListener.isRunning,
            "batteryPercent" to battery.first,
            "isCharging" to battery.second
        )
        sendReply(payload)
    }

    private fun sendTelemetry() {
        val battery = getBatteryInfo()
        val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
        val payload = mapOf(
            "type" to "telemetry",
            "batteryPercent" to battery.first,
            "isCharging" to battery.second,
            "isScreenOn" to pm.isInteractive,
            "currentPackage" to (AlitaAccessibilityService.instance?.currentPackage ?: ""),
            "accessibilityActive" to AlitaAccessibilityService.isRunning,
            "notificationListenerActive" to AlitaNotificationListener.isRunning,
            "timestamp" to System.currentTimeMillis()
        )
        sendReply(payload)
    }

    private fun getBatteryInfo(): Pair<Int, Boolean> {
        val filter = IntentFilter(Intent.ACTION_BATTERY_CHANGED)
        val batteryStatus = registerReceiver(null, filter)
        val level = batteryStatus?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1
        val scale = batteryStatus?.getIntExtra(BatteryManager.EXTRA_SCALE, -1) ?: -1
        val pct = if (level >= 0 && scale > 0) (level * 100) / scale else -1

        val status = batteryStatus?.getIntExtra(BatteryManager.EXTRA_STATUS, -1) ?: -1
        val isCharging = status == BatteryManager.BATTERY_STATUS_CHARGING || status == BatteryManager.BATTERY_STATUS_FULL

        return Pair(pct, isCharging)
    }

    private fun sendReply(data: Map<String, Any?>) {
        val json = gson.toJson(data)
        webSocket?.send(json)
    }

    private fun sendServiceError(commandId: String, msg: String) {
        sendReply(mapOf(
            "type" to "command_result",
            "id" to commandId,
            "success" to false,
            "error" to msg
        ))
    }

    private fun notifyActivityStatus(status: String) {
        val intent = Intent("ai.alita.companion.CONNECTION_STATE").apply {
            putExtra("status", status)
        }
        sendBroadcast(intent)
    }

    // ==========================================
    // NOTIFICATION HELPERS
    // ==========================================

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                getString(R.string.foreground_service_channel_name),
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = getString(R.string.foreground_service_channel_desc)
            }
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(channel)
        }
    }

    private fun buildForegroundNotification(statusText: String): android.app.Notification {
        val pendingIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE
        )

        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("MJ Desktop Companion")
            .setContentText(statusText)
            .setSmallIcon(android.R.drawable.stat_notify_sync)
            .setContentIntent(pendingIntent)
            .setOngoing(true)
            .build()
    }

    private fun updateForegroundNotification(statusText: String) {
        val notification = buildForegroundNotification(statusText)
        val manager = getSystemService(NotificationManager::class.java)
        manager.notify(NOTIFICATION_ID, notification)
    }
}

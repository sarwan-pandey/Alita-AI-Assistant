package ai.alita.companion

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.SharedPreferences
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.widget.Button
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import com.google.android.material.textfield.TextInputEditText

/**
 * MainActivity
 * Setup, connection management, permission checking, and diagnostic control.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var prefs: SharedPreferences

    private lateinit var etPcIp: TextInputEditText
    private lateinit var etPcPort: TextInputEditText
    private lateinit var btnToggleConnect: Button
    private lateinit var tvConnectionStatus: TextView
    private lateinit var tvBridgeLatency: TextView

    private lateinit var tvA11yStatus: TextView
    private lateinit var btnEnableA11y: Button

    private lateinit var tvNotifStatus: TextView
    private lateinit var btnEnableNotif: Button

    private lateinit var tvBatteryStatus: TextView
    private lateinit var btnIgnoreBattery: Button

    private lateinit var btnDumpTree: Button
    private lateinit var btnTestHome: Button
    private lateinit var btnTestNotif: Button
    private lateinit var tvLogs: TextView

    private val connectionReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            val status = intent?.getStringExtra("status") ?: return
            updateStatusUi(status)
            appendLog("[STATUS] Connection status updated: $status")
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        prefs = getSharedPreferences("alita_companion_prefs", Context.MODE_PRIVATE)

        bindViews()
        loadSavedConfig()
        setupListeners()
    }

    override fun onResume() {
        super.onResume()
        checkPermissions()
        val filter = IntentFilter("ai.alita.companion.CONNECTION_STATE")
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            registerReceiver(connectionReceiver, filter, Context.RECEIVER_NOT_EXPORTED)
        } else {
            registerReceiver(connectionReceiver, filter)
        }
        updateStatusUi(if (AlitaPhoneBridgeService.isConnected) "CONNECTED" else "OFFLINE")
    }

    override fun onPause() {
        super.onPause()
        try {
            unregisterReceiver(connectionReceiver)
        } catch (_: Exception) {}
    }

    private fun bindViews() {
        etPcIp = findViewById(R.id.etPcIp)
        etPcPort = findViewById(R.id.etPcPort)
        btnToggleConnect = findViewById(R.id.btnToggleConnect)
        tvConnectionStatus = findViewById(R.id.tvConnectionStatus)
        tvBridgeLatency = findViewById(R.id.tvBridgeLatency)

        tvA11yStatus = findViewById(R.id.tvA11yStatus)
        btnEnableA11y = findViewById(R.id.btnEnableA11y)

        tvNotifStatus = findViewById(R.id.tvNotifStatus)
        btnEnableNotif = findViewById(R.id.btnEnableNotif)

        tvBatteryStatus = findViewById(R.id.tvBatteryStatus)
        btnIgnoreBattery = findViewById(R.id.btnIgnoreBattery)

        btnDumpTree = findViewById(R.id.btnDumpTree)
        btnTestHome = findViewById(R.id.btnTestHome)
        btnTestNotif = findViewById(R.id.btnTestNotif)
        tvLogs = findViewById(R.id.tvLogs)
    }

    private fun loadSavedConfig() {
        val savedIp = prefs.getString("pc_ip", "praising-cahoots-safely.ngrok-free.dev")
        val savedPort = prefs.getInt("pc_port", 443)
        etPcIp.setText(savedIp)
        etPcPort.setText(savedPort.toString())
    }

    private fun setupListeners() {
        btnToggleConnect.setOnClickListener {
            val ip = etPcIp.text.toString().trim()
            val portStr = etPcPort.text.toString().trim()
            val isDomain = ip.contains(".ngrok") || ip.contains(".dev") || ip.contains(".trycloudflare.com") || ip.contains("://") || ip.contains(".com") || ip.contains(".net") || ip.contains(".app")
            val defaultPort = if (isDomain) 443 else 8000
            val port = portStr.toIntOrNull() ?: defaultPort

            prefs.edit().putString("pc_ip", ip).putInt("pc_port", port).apply()

            if (AlitaPhoneBridgeService.isConnected) {
                val stopIntent = Intent(this, AlitaPhoneBridgeService::class.java).apply {
                    action = AlitaPhoneBridgeService.ACTION_STOP
                }
                startService(stopIntent)
                appendLog("[BRIDGE] Disconnecting service...")
            } else {
                val startIntent = Intent(this, AlitaPhoneBridgeService::class.java).apply {
                    action = AlitaPhoneBridgeService.ACTION_START
                    putExtra(AlitaPhoneBridgeService.EXTRA_HOST, ip)
                    putExtra(AlitaPhoneBridgeService.EXTRA_PORT, port)
                }
                ContextCompat.startForegroundService(this, startIntent)
                appendLog("[BRIDGE] Launching bridge service to $ip:$port...")
            }
        }

        btnEnableA11y.setOnClickListener {
            val intent = Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)
            startActivity(intent)
            Toast.makeText(this, "Enable 'MJ Automation Service'", Toast.LENGTH_LONG).show()
        }

        btnEnableNotif.setOnClickListener {
            val intent = Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS)
            startActivity(intent)
            Toast.makeText(this, "Enable 'MJ Message Bridge'", Toast.LENGTH_LONG).show()
        }

        btnIgnoreBattery.setOnClickListener {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                val intent = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS).apply {
                    data = Uri.parse("package:$packageName")
                }
                startActivity(intent)
            }
        }

        btnDumpTree.setOnClickListener {
            val a11y = AlitaAccessibilityService.instance
            if (a11y != null) {
                val tree = a11y.dumpViewTree()
                val count = tree["nodeCount"]
                val pkg = tree["package"]
                appendLog("[VIEW-TREE] Pkg: $pkg, Nodes captured: $count")
            } else {
                appendLog("[ERROR] Accessibility service not running!")
            }
        }

        btnTestHome.setOnClickListener {
            val a11y = AlitaAccessibilityService.instance
            if (a11y != null) {
                val success = a11y.performGlobal("home")
                appendLog("[NAV] Global Home triggered: $success")
            } else {
                appendLog("[ERROR] Accessibility service not running!")
            }
        }

        btnTestNotif.setOnClickListener {
            if (AlitaPhoneBridgeService.isConnected) {
                AlitaPhoneBridgeService.instance?.broadcastEvent(mapOf(
                    "type" to "ping",
                    "timestamp" to System.currentTimeMillis()
                ))
                appendLog("[BRIDGE] Ping sent to PC")
            } else {
                appendLog("[WARN] Bridge is offline. Cannot ping PC.")
            }
        }
    }

    private fun checkPermissions() {
        // 1. Accessibility Service Check
        val a11yActive = AlitaAccessibilityService.isRunning
        if (a11yActive) {
            tvA11yStatus.text = "Active & Running"
            tvA11yStatus.setTextColor(ContextCompat.getColor(this, R.color.success))
            btnEnableA11y.isEnabled = false
            btnEnableA11y.text = "Granted"
        } else {
            tvA11yStatus.text = "Disabled"
            tvA11yStatus.setTextColor(ContextCompat.getColor(this, R.color.error))
            btnEnableA11y.isEnabled = true
            btnEnableA11y.text = "Enable"
        }

        // 2. Notification Listener Check
        val notifActive = AlitaNotificationListener.isRunning
        if (notifActive) {
            tvNotifStatus.text = "Active & Running"
            tvNotifStatus.setTextColor(ContextCompat.getColor(this, R.color.success))
            btnEnableNotif.isEnabled = false
            btnEnableNotif.text = "Granted"
        } else {
            tvNotifStatus.text = "Disabled"
            tvNotifStatus.setTextColor(ContextCompat.getColor(this, R.color.error))
            btnEnableNotif.isEnabled = true
            btnEnableNotif.text = "Enable"
        }

        // 3. Battery Optimization Check
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
            val isIgnored = pm.isIgnoringBatteryOptimizations(packageName)
            if (isIgnored) {
                tvBatteryStatus.text = "Exempted (Persistent)"
                tvBatteryStatus.setTextColor(ContextCompat.getColor(this, R.color.success))
                btnIgnoreBattery.isEnabled = false
                btnIgnoreBattery.text = "Allowed"
            } else {
                tvBatteryStatus.text = "Optimized (May Sleep)"
                tvBatteryStatus.setTextColor(ContextCompat.getColor(this, R.color.warning))
                btnIgnoreBattery.isEnabled = true
                btnIgnoreBattery.text = "Allow"
            }
        }
    }

    private fun updateStatusUi(status: String) {
        if (status == "CONNECTED") {
            tvConnectionStatus.text = "CONNECTED"
            tvConnectionStatus.setTextColor(ContextCompat.getColor(this, R.color.success))
            btnToggleConnect.text = "Disconnect"
        } else {
            tvConnectionStatus.text = "OFFLINE"
            tvConnectionStatus.setTextColor(ContextCompat.getColor(this, R.color.error))
            btnToggleConnect.text = "Connect"
        }
    }

    private fun appendLog(msg: String) {
        runOnUiThread {
            val current = tvLogs.text.toString()
            val updated = "$msg\n$current".take(2000)
            tvLogs.text = updated
        }
    }
}

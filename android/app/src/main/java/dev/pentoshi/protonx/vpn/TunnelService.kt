package dev.pentoshi.protonx.vpn

import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.IBinder
import androidx.core.content.ContextCompat
import dev.pentoshi.protonx.ProtonXApp
import dev.pentoshi.protonx.core.Phase
import dev.pentoshi.protonx.core.Target
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

/**
 * The only component that mutates the tunnel. It stays in the foreground while
 * connected so Android keeps the WireGuard backend (same process) alive, and
 * stops itself as soon as nothing is up, which keeps idle cost at zero.
 */
class TunnelService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private lateinit var tunnel: TunnelController

    override fun onCreate() {
        super.onCreate()
        tunnel = ProtonXApp.of(this).tunnel
        Notifications.createChannel(this)
        startForeground(Notifications.ID, Notifications.build(this, Phase.CONNECTING, null, null))
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val action = intent?.action
        if (action == null) {
            finishIfIdle()
            return START_NOT_STICKY
        }
        val country = intent.getStringExtra(EXTRA_COUNTRY)
        val server = intent.getStringExtra(EXTRA_SERVER)
        scope.launch {
            handle(action, country, server)
            finishIfIdle()
        }
        return START_NOT_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    private suspend fun handle(action: String, country: String?, server: String?) {
        when (action) {
            ACTION_CONNECT_FASTEST -> connect(Target.Fastest)
            ACTION_CONNECT_LAST -> connect(Target.Last)
            ACTION_CONNECT_SERVER -> connect(
                if (country != null && server != null) Target.Server(country, server)
                else Target.Last,
            )
            ACTION_DISCONNECT -> tunnel.disconnect()
            ACTION_TOGGLE -> if (isActive()) tunnel.disconnect() else connect(Target.Last)
        }
        StateBroadcast.send(this)
    }

    private suspend fun connect(target: Target) {
        Notifications.update(this, Phase.CONNECTING, null, null)
        val snapshot = runCatching { tunnel.connect(target) }.getOrNull()
        val phase = snapshot?.phase ?: Phase.ERROR
        Notifications.update(this, phase, snapshot?.server?.label, snapshot?.error ?: tunnel.store.lastError)
    }

    private fun isActive(): Boolean {
        val phase = tunnel.store.phase
        return phase == Phase.CONNECTED || phase == Phase.CONNECTING
    }

    private fun finishIfIdle() {
        if (isActive() || tunnel.store.phase == Phase.DISCONNECTING) return
        // An error notification should survive the service so the user sees why.
        stopForeground(if (tunnel.store.phase == Phase.ERROR) STOP_FOREGROUND_DETACH else STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    companion object {
        const val ACTION_CONNECT_FASTEST = "dev.pentoshi.protonx.CONNECT_FASTEST"
        const val ACTION_CONNECT_LAST = "dev.pentoshi.protonx.CONNECT_LAST"
        const val ACTION_CONNECT_SERVER = "dev.pentoshi.protonx.CONNECT_SERVER"
        const val ACTION_DISCONNECT = "dev.pentoshi.protonx.DISCONNECT"
        const val ACTION_TOGGLE = "dev.pentoshi.protonx.TOGGLE"
        const val EXTRA_COUNTRY = "country"
        const val EXTRA_SERVER = "server"

        fun start(context: Context, action: String, country: String? = null, server: String? = null) {
            val intent = Intent(context, TunnelService::class.java).setAction(action)
            if (country != null) intent.putExtra(EXTRA_COUNTRY, country)
            if (server != null) intent.putExtra(EXTRA_SERVER, server)
            ContextCompat.startForegroundService(context, intent)
        }
    }
}

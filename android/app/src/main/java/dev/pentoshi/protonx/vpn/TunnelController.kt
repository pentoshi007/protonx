package dev.pentoshi.protonx.vpn

import android.content.Context
import com.wireguard.android.backend.BackendException
import com.wireguard.android.backend.GoBackend
import com.wireguard.android.backend.Tunnel
import com.wireguard.config.Config
import dev.pentoshi.protonx.core.Entry
import dev.pentoshi.protonx.core.Identity
import dev.pentoshi.protonx.core.KeyConflict
import dev.pentoshi.protonx.core.Logical
import dev.pentoshi.protonx.core.Logicals
import dev.pentoshi.protonx.core.Phase
import dev.pentoshi.protonx.core.ProtonApi
import dev.pentoshi.protonx.core.SavedServer
import dev.pentoshi.protonx.core.Selection
import dev.pentoshi.protonx.core.Session
import dev.pentoshi.protonx.core.SessionExpired
import dev.pentoshi.protonx.core.SignInOutcome
import dev.pentoshi.protonx.core.Snapshot
import dev.pentoshi.protonx.core.Target
import dev.pentoshi.protonx.core.Traffic
import dev.pentoshi.protonx.core.WgConfig
import dev.pentoshi.protonx.data.CatalogStore
import dev.pentoshi.protonx.data.StateStore
import dev.pentoshi.protonx.net.FlowProbe
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

class TunnelFailure(message: String) : Exception(message)

class TunnelController(context: Context) {
    private val app = context.applicationContext
    val store = StateStore(app)
    private val catalog = CatalogStore(app)
    private val api = ProtonApi(sessionProvider = { store.session() }, sessionSaver = { store.saveSession(it) })
    private val backend: GoBackend by lazy { GoBackend(app) }
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val mutex = Mutex()
    private var watchdog: Job? = null

    private val tunnel = object : Tunnel {
        override fun getName(): String = TUNNEL_NAME

        override fun onStateChange(newState: Tunnel.State) {
            // Revoking the VPN from system settings lands here; reflect it honestly.
            if (newState == Tunnel.State.DOWN && store.phase == Phase.CONNECTED) {
                store.phase = Phase.IDLE
                store.setCurrentServer(null)
                Notifications.cancel(app)
                StateBroadcast.send(app)
            }
        }
    }

    suspend fun connect(target: Target): Snapshot = mutex.withLock {
        if (store.session() == null) throw SessionExpired("Sign in to Proton first.")
        store.phase = Phase.CONNECTING
        store.lastError = null
        StateBroadcast.send(app)
        try {
            val logical = resolve(target)
            val entry = logical.wireguardEntries.firstOrNull()
                ?: throw TunnelFailure("${logical.displayName()} has no WireGuard entry.")
            val identity = acceptedIdentity()
            if (!bringUp(entry, identity)) {
                // A handshake that forwards nothing means Proton did not bind this
                // key to the session, so rotate it once and retry.
                if (!bringUp(entry, rotateIdentity())) throw TunnelFailure(FLOW_ERROR)
            }
            val server = SavedServer.of(logical)
            store.setCurrentServer(server)
            store.rememberServer(server)
            store.connectedAt = System.currentTimeMillis()
            store.phase = Phase.CONNECTED
            startWatchdog()
            Notifications.update(app, Phase.CONNECTED, server.label, null)
            StateBroadcast.send(app)
            store.snapshot()
        } catch (error: Exception) {
            stopTunnel()
            Notifications.cancel(app)
            store.phase = Phase.ERROR
            store.lastError = describe(error)
            StateBroadcast.send(app)
            throw TunnelFailure(store.lastError ?: "could not connect")
        }
    }

    suspend fun disconnect(): Snapshot = mutex.withLock {
        store.phase = Phase.DISCONNECTING
        StateBroadcast.send(app)
        stopTunnel()
        Notifications.cancel(app)
        StateBroadcast.send(app)
        store.snapshot()
    }

    suspend fun reconcile() {
        if (store.phase != Phase.CONNECTED) return
        val running = withContext(Dispatchers.IO) {
            runCatching { backend.getState(tunnel) == Tunnel.State.UP }.getOrDefault(false)
        }
        if (running) return
        store.phase = Phase.IDLE
        store.setCurrentServer(null)
        Notifications.cancel(app)
        StateBroadcast.send(app)
    }

    /** Safe from any dispatcher: the HTTP work happens off the main thread. */
    suspend fun loadServers(force: Boolean): List<Logical> = withContext(Dispatchers.IO) {
        val cached = catalog.load()
        if (!force && cached != null) return@withContext cached.servers
        val payload = api.logicals()
        val servers = Logicals.parse(payload)
        if (servers.isEmpty()) throw TunnelFailure("Proton returned no servers.")
        val now = System.currentTimeMillis()
        catalog.save(payload, now)
        store.catalogFetchedAt = now
        servers
    }

    fun cachedServers(): List<Logical> = catalog.load()?.servers ?: emptyList()

    fun traffic(): Traffic = runCatching {
        val statistics = backend.getStatistics(tunnel)
        Traffic(statistics.totalRx(), statistics.totalTx())
    }.getOrDefault(Traffic(0, 0))

    suspend fun signIn(username: String, password: String): SignInOutcome = api.signIn(username, password)

    suspend fun finishTwoFactor(session: Session, code: String): Session = api.finishTwoFactor(session, code)

    fun signOut() {
        store.clearSession()
        StateBroadcast.send(app)
    }

    private suspend fun resolve(target: Target): Logical {
        val pool = loadServers(force = false)
        val includePaid = store.showPaid
        return when (target) {
            Target.Fastest -> Selection.fastest(pool, includePaid)
                ?: throw TunnelFailure("No free server is available right now.")

            Target.Last -> store.lastServer()
                ?.let { last ->
                    Selection.byName(pool, last.server, includePaid = includePaid)
                        ?: Selection.fastest(pool, includePaid)
                }
                ?: Selection.fastest(pool, includePaid)
                ?: throw TunnelFailure("No free server is available right now.")

            is Target.Server -> Selection.byName(pool, target.name, target.country, includePaid)
                ?: Selection.serversIn(pool, target.country, includePaid).firstOrNull()
                ?: throw TunnelFailure("${target.country} has no available server.")
        }
    }

    private fun acceptedIdentity(): Identity {
        val identity = store.identity()
        return try {
            api.registerKey(identity.ed25519PublicKey)
            identity
        } catch (conflict: KeyConflict) {
            rotateIdentity()
        }
    }

    private fun rotateIdentity(): Identity {
        val replacement = Identity.create()
        // Persist only after Proton accepts the replacement, so a failure keeps the old key.
        api.registerKey(replacement.ed25519PublicKey)
        store.saveIdentity(replacement)
        return replacement
    }

    private suspend fun bringUp(entry: Entry, identity: Identity): Boolean {
        val config = WgConfig.render(identity.x25519PrivateKey, entry.x25519, entry.endpointHost, entry.port)
        backend.setState(tunnel, Tunnel.State.UP, Config.parse(config.reader().buffered()))
        if (awaitTraffic()) return true
        backend.setState(tunnel, Tunnel.State.DOWN, null)
        return false
    }

    /**
     * Pumps both proof channels until one answers. A DNS packet to the in-tunnel
     * resolver is cheapest; HTTPS is the fallback when that resolver stays quiet.
     */
    private suspend fun awaitTraffic(timeoutMs: Long = CONNECT_PROOF_MS): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        var round = 0
        while (System.currentTimeMillis() < deadline) {
            if (FlowProbe.reachesInternet(timeoutMs = 1_200)) return true
            if (round % 2 == 1 && FlowProbe.httpsReachable(timeoutMs = 3_500)) return true
            round++
            delay(500)
        }
        return FlowProbe.httpsReachable(timeoutMs = 4_000)
    }

    private suspend fun stopTunnel() {
        watchdog?.cancel()
        watchdog = null
        runCatching { backend.setState(tunnel, Tunnel.State.DOWN, null) }
        store.setCurrentServer(null)
        store.phase = Phase.IDLE
    }

    private fun startWatchdog() {
        watchdog?.cancel()
        watchdog = scope.launch {
            var elapsed = 0L
            for (checkpoint in WATCHDOG_MS) {
                delay(checkpoint - elapsed)
                elapsed = checkpoint
                if (store.phase != Phase.CONNECTED) return@launch
                if (!awaitTraffic(WATCHDOG_PROOF_MS)) {
                    dropDeadTunnel()
                    return@launch
                }
            }
        }
    }

    private suspend fun dropDeadTunnel() = mutex.withLock {
        if (store.phase != Phase.CONNECTED) return@withLock
        stopTunnel()
        store.phase = Phase.ERROR
        store.lastError = DROPPED_ERROR
        Notifications.update(app, Phase.ERROR, null, DROPPED_ERROR)
        StateBroadcast.send(app)
    }

    private fun describe(error: Exception): String = when {
        error is BackendException && error.reason == BackendException.Reason.VPN_NOT_AUTHORIZED ->
            "Android blocked the VPN. Open ProtonX and allow the VPN request."
        else -> error.message ?: error.javaClass.simpleName
    }

    companion object {
        const val TUNNEL_NAME = "protonx"
        const val FLOW_ERROR = "The tunnel is not carrying traffic. Proton refused this device key."
        const val DROPPED_ERROR = "The tunnel stopped carrying traffic. Reconnect to continue."
        private const val CONNECT_PROOF_MS = 12_000L
        private const val WATCHDOG_PROOF_MS = 8_000L
        private val WATCHDOG_MS = longArrayOf(5_000, 15_000, 30_000)
    }
}

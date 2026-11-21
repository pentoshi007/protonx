package dev.pentoshi.protonx.ui

import android.Manifest
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.view.View
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import androidx.core.widget.doAfterTextChanged
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import dev.pentoshi.protonx.ProtonXApp
import dev.pentoshi.protonx.R
import dev.pentoshi.protonx.core.CountryRow
import dev.pentoshi.protonx.core.Logical
import dev.pentoshi.protonx.core.Phase
import dev.pentoshi.protonx.core.Selection
import dev.pentoshi.protonx.core.Snapshot
import dev.pentoshi.protonx.data.StateStore
import dev.pentoshi.protonx.databinding.ActivityMainBinding
import dev.pentoshi.protonx.vpn.StateBroadcast
import dev.pentoshi.protonx.vpn.TunnelService
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class MainActivity : ConsentActivity() {
    private lateinit var binding: ActivityMainBinding
    private lateinit var store: StateStore
    private val tunnel by lazy { ProtonXApp.of(this).tunnel }
    private val countryAdapter = CountryAdapter(::openCountry)
    private var servers: List<Logical> = emptyList()
    private var snapshot = Snapshot(Phase.IDLE, null, null, 0)
    private var statsJob: Job? = null

    private val notificationPermission = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { }

    private val stateReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) = render()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        // The compat splash screen must be installed before the activity is created.
        installSplashScreen()
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        applyInsets(binding.root)
        store = StateStore(this)

        binding.countryList.layoutManager = LinearLayoutManager(this)
        binding.countryList.adapter = countryAdapter
        binding.toggleButton.setOnClickListener { toggle() }
        binding.fastestCard.setOnClickListener { connect(TunnelService.ACTION_CONNECT_FASTEST) }
        binding.lastCard.setOnClickListener { connect(TunnelService.ACTION_CONNECT_LAST) }
        binding.searchInput.doAfterTextChanged { renderCountries() }
        binding.toolbar.setOnMenuItemClickListener { item ->
            when (item.itemId) {
                R.id.action_refresh -> refreshServers(force = true)
                R.id.action_account -> showAccount()
                R.id.action_paid -> togglePaid(item)
            }
            true
        }
        requestNotificationPermission()
        render()
    }

    override fun onStart() {
        super.onStart()
        ContextCompat.registerReceiver(
            this,
            stateReceiver,
            IntentFilter(StateBroadcast.ACTION_STATE),
            ContextCompat.RECEIVER_NOT_EXPORTED,
        )
        refresh()
    }

    override fun onResume() {
        super.onResume()
        syncStatsJob()
    }

    override fun onPause() {
        statsJob?.cancel()
        statsJob = null
        super.onPause()
    }

    override fun onStop() {
        runCatching { unregisterReceiver(stateReceiver) }
        super.onStop()
    }

    private fun requestNotificationPermission() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return
        val granted = checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED
        if (!granted) notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
    }

    private fun refresh() {
        lifecycleScope.launch {
            servers = tunnel.cachedServers()
            render()
            if (!store.signedIn()) return@launch
            tunnel.reconcile()
            runCatching { tunnel.loadServers(force = false) }
                .onSuccess { servers = it; render() }
                .onFailure { showError(it.message ?: it.javaClass.simpleName) }
        }
    }
    private fun refreshServers(force: Boolean) {
        if (!store.signedIn()) return openSignIn()
        lifecycleScope.launch {
            runCatching { tunnel.loadServers(force) }
                .onSuccess { servers = it; render() }
                .onFailure { showError(it.message) }
        }
    }

    private fun togglePaid(item: android.view.MenuItem) {
        store.showPaid = !store.showPaid
        item.isChecked = store.showPaid
        render()
    }

    private fun render() {
        snapshot = store.snapshot()
        val signedIn = store.signedIn()
        val includePaid = store.showPaid
        val connected = snapshot.phase == Phase.CONNECTED
        val busy = snapshot.phase == Phase.CONNECTING || snapshot.phase == Phase.DISCONNECTING

        binding.statusTitle.setText(
            when (snapshot.phase) {
                Phase.CONNECTED -> R.string.status_connected
                Phase.CONNECTING -> R.string.status_connecting
                Phase.DISCONNECTING -> R.string.status_disconnecting
                else -> R.string.status_disconnected
            },
        )
        binding.statusDetail.text = when {
            !signedIn -> getString(R.string.signed_out_body)
            connected -> listOfNotNull(snapshot.server?.label, snapshot.server?.city)
                .filter { it.isNotBlank() }.distinct().joinToString(" · ")
            snapshot.phase == Phase.ERROR && !snapshot.error.isNullOrBlank() -> snapshot.error
            else -> getString(R.string.status_detail_idle)
        }
        binding.statusIcon.setColorFilter(
            ContextCompat.getColor(this, if (connected) R.color.success else R.color.brand),
        )
        binding.statusRing.setPhase(snapshot.phase)

        binding.toggleButton.setText(
            when {
                !signedIn -> R.string.sign_in_action
                connected || snapshot.phase == Phase.CONNECTING -> R.string.action_disconnect
                else -> R.string.action_connect
            },
        )
        binding.toggleButton.isEnabled = !busy

        binding.fastestDetail.text = Selection.fastest(servers, includePaid)?.let { fastest ->
            "${fastest.displayName()} · ${getString(R.string.server_load, fastest.load)}"
        } ?: getString(R.string.fastest_subtitle)
        binding.lastDetail.text = store.lastServer()?.label ?: getString(R.string.last_subtitle)
        binding.toolbar.menu.findItem(R.id.action_paid)?.isChecked = includePaid

        val showList = signedIn
        binding.searchBox.visibility = if (showList) View.VISIBLE else View.GONE
        binding.listLabel.visibility = if (showList) View.VISIBLE else View.GONE
        binding.countryList.visibility = if (showList) View.VISIBLE else View.GONE
        renderCountries()
        binding.statusTraffic.visibility = if (connected) View.VISIBLE else View.GONE
        syncStatsJob()
    }

    private fun renderCountries() {
        val query = binding.searchInput.text?.toString().orEmpty().trim()
        val rows = Selection.countries(servers, store.showPaid).filter { row ->
            query.isEmpty() ||
                row.name.contains(query, ignoreCase = true) ||
                row.code.contains(query, ignoreCase = true)
        }
        countryAdapter.submit(rows)
        binding.emptyList.visibility = if (rows.isEmpty() && store.signedIn()) View.VISIBLE else View.GONE
    }

    /** Traffic is polled only while a tunnel is up and this screen is visible. */
    private fun syncStatsJob() {
        if (snapshot.phase != Phase.CONNECTED || !lifecycle.currentState.isAtLeast(androidx.lifecycle.Lifecycle.State.RESUMED)) {
            statsJob?.cancel()
            statsJob = null
            return
        }
        if (statsJob?.isActive == true) return
        statsJob = lifecycleScope.launch {
            while (isActive) {
                updateTraffic()
                delay(1_000)
            }
        }
    }

    private suspend fun updateTraffic() {
        val traffic = withContext(Dispatchers.IO) { tunnel.traffic() }
        if (snapshot.phase != Phase.CONNECTED) return
        val uptime = System.currentTimeMillis() - snapshot.since
        binding.statusTraffic.text = getString(
            R.string.traffic_format,
            bytesLabel(traffic.received),
            bytesLabel(traffic.sent),
        ) + "  ·  " + durationLabel(uptime)
    }

    private fun toggle() {
        if (!store.signedIn()) return openSignIn()
        if (snapshot.phase == Phase.CONNECTED || snapshot.phase == Phase.CONNECTING) {
            TunnelService.start(this, TunnelService.ACTION_DISCONNECT)
        } else {
            connect(TunnelService.ACTION_CONNECT_LAST)
        }
    }

    private fun connect(action: String, country: String? = null, server: String? = null) {
        if (!store.signedIn()) return openSignIn()
        withConsent { TunnelService.start(this, action, country, server) }
    }

    private fun openSignIn() {
        startActivity(Intent(this, SignInActivity::class.java))
    }

    private fun openCountry(row: CountryRow) {
        startActivity(
            Intent(this, CountryActivity::class.java)
                .putExtra(CountryActivity.EXTRA_COUNTRY, row.code)
                .putExtra(CountryActivity.EXTRA_NAME, row.name),
        )
    }

    private fun showAccount() {
        val signedIn = store.signedIn()
        val message = if (signedIn) {
            getString(R.string.signed_in_as, store.session()?.username ?: "Proton")
        } else {
            getString(R.string.signed_out_body)
        }
        MaterialAlertDialogBuilder(this)
            .setTitle(R.string.account)
            .setMessage(message)
            .setPositiveButton(if (signedIn) R.string.sign_out else R.string.sign_in_action) { _, _ ->
                if (signedIn) {
                    TunnelService.start(this, TunnelService.ACTION_DISCONNECT)
                    tunnel.signOut()
                    render()
                } else {
                    openSignIn()
                }
            }
            .setNegativeButton(R.string.action_cancel, null)
            .show()
    }

    private fun showError(message: String?) {
        if (!message.isNullOrBlank()) {
            android.util.Log.w("ProtonX", "server list: $message")
            binding.statusDetail.text = message
        }
    }
}

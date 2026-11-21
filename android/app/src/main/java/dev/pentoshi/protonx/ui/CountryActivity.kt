package dev.pentoshi.protonx.ui

import android.os.Bundle
import android.view.View
import androidx.recyclerview.widget.LinearLayoutManager
import dev.pentoshi.protonx.ProtonXApp
import dev.pentoshi.protonx.R
import dev.pentoshi.protonx.core.Logical
import dev.pentoshi.protonx.core.Selection
import dev.pentoshi.protonx.databinding.ActivityCountryBinding
import dev.pentoshi.protonx.vpn.TunnelService

class CountryActivity : ConsentActivity() {
    private lateinit var binding: ActivityCountryBinding
    private val tunnel by lazy { ProtonXApp.of(this).tunnel }
    private lateinit var country: String
    private val adapter by lazy {
        ServerAdapter(active = { tunnel.store.currentServer()?.label }, onClick = ::connect)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityCountryBinding.inflate(layoutInflater)
        setContentView(binding.root)
        applyInsets(binding.root)
        country = intent.getStringExtra(EXTRA_COUNTRY).orEmpty()
        val name = intent.getStringExtra(EXTRA_NAME) ?: country
        binding.toolbar.title = getString(R.string.servers_title, name)
        binding.toolbar.setNavigationOnClickListener { finish() }
        binding.serverList.layoutManager = LinearLayoutManager(this)
        binding.serverList.adapter = adapter

        val servers = Selection.serversIn(tunnel.cachedServers(), country, tunnel.store.showPaid)
        adapter.submit(servers)
        binding.emptyState.visibility = if (servers.isEmpty()) View.VISIBLE else View.GONE
    }

    private fun connect(logical: Logical) {
        withConsent {
            TunnelService.start(this, TunnelService.ACTION_CONNECT_SERVER, country, logical.displayName())
            finish()
        }
    }

    companion object {
        const val EXTRA_COUNTRY = "country"
        const val EXTRA_NAME = "country_name"
    }
}

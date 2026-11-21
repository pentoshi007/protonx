package dev.pentoshi.protonx.tile

import android.os.Build
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService
import dev.pentoshi.protonx.R
import dev.pentoshi.protonx.core.Phase
import dev.pentoshi.protonx.data.StateStore
import dev.pentoshi.protonx.vpn.TunnelService

abstract class BaseTileService : TileService() {

    protected abstract fun connectAction(): String

    override fun onStartListening() {
        super.onStartListening()
        refresh()
    }

    override fun onClick() {
        super.onClick()
        val phase = StateStore(this).phase
        val running = phase == Phase.CONNECTED || phase == Phase.CONNECTING
        TunnelService.start(this, if (running) TunnelService.ACTION_DISCONNECT else connectAction())
        refresh()
    }

    private fun refresh() {
        val tile = qsTile ?: return
        val store = StateStore(this)
        val snapshot = store.snapshot()
        tile.state = when {
            !store.signedIn() -> Tile.STATE_UNAVAILABLE
            snapshot.phase == Phase.CONNECTED -> Tile.STATE_ACTIVE
            snapshot.phase == Phase.CONNECTING -> Tile.STATE_ACTIVE
            else -> Tile.STATE_INACTIVE
        }
        tile.label = if (store.signedIn()) getString(R.string.app_name) else getString(R.string.tile_needs_sign_in)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            // Tile.subtitle only exists from Android 10.
            tile.subtitle = when {
                !store.signedIn() -> getString(R.string.tile_needs_sign_in)
                snapshot.phase == Phase.CONNECTED -> snapshot.server?.label ?: getString(R.string.status_connected)
                snapshot.phase == Phase.CONNECTING -> getString(R.string.status_connecting)
                else -> getString(R.string.status_disconnected)
            }
        }
        tile.updateTile()
    }
}

class FastestTileService : BaseTileService() {
    override fun connectAction(): String = TunnelService.ACTION_CONNECT_FASTEST
}

class LastTileService : BaseTileService() {
    override fun connectAction(): String = TunnelService.ACTION_CONNECT_LAST
}

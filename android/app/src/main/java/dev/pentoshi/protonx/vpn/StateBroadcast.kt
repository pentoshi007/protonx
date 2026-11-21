package dev.pentoshi.protonx.vpn

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.service.quicksettings.TileService
import dev.pentoshi.protonx.tile.FastestTileService
import dev.pentoshi.protonx.tile.LastTileService
import dev.pentoshi.protonx.widget.StatusWidgetProvider

/** One signal that every surface listens to, so nothing has to poll. */
object StateBroadcast {
    const val ACTION_STATE = "dev.pentoshi.protonx.STATE_CHANGED"

    fun send(context: Context) {
        val app = context.applicationContext
        app.sendBroadcast(Intent(ACTION_STATE).setPackage(app.packageName))
        StatusWidgetProvider.updateAll(app)
        refreshTiles(app)
    }

    private fun refreshTiles(context: Context) {
        TileService.requestListeningState(context, ComponentName(context, FastestTileService::class.java))
        TileService.requestListeningState(context, ComponentName(context, LastTileService::class.java))
    }
}

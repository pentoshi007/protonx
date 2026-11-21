package dev.pentoshi.protonx

import android.app.Application
import android.content.Context
import dev.pentoshi.protonx.vpn.Notifications
import dev.pentoshi.protonx.vpn.TunnelController

class ProtonXApp : Application() {
    val tunnel: TunnelController by lazy { TunnelController(this) }

    override fun onCreate() {
        super.onCreate()
        Notifications.createChannel(this)
    }

    companion object {
        fun of(context: Context): ProtonXApp = context.applicationContext as ProtonXApp
    }
}

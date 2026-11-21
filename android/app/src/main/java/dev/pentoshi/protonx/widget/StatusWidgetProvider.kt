package dev.pentoshi.protonx.widget

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.widget.RemoteViews
import dev.pentoshi.protonx.R
import dev.pentoshi.protonx.core.Phase
import dev.pentoshi.protonx.data.StateStore
import dev.pentoshi.protonx.ui.MainActivity
import dev.pentoshi.protonx.vpn.StateBroadcast
import dev.pentoshi.protonx.vpn.TunnelService

class StatusWidgetProvider : AppWidgetProvider() {

    override fun onUpdate(context: Context, manager: AppWidgetManager, appWidgetIds: IntArray) {
        appWidgetIds.forEach { render(context, manager, it) }
    }

    override fun onReceive(context: Context, intent: Intent) {
        super.onReceive(context, intent)
        if (intent.action == StateBroadcast.ACTION_STATE) updateAll(context)
    }

    companion object {
        fun updateAll(context: Context) {
            val manager = AppWidgetManager.getInstance(context) ?: return
            val ids = manager.getAppWidgetIds(ComponentName(context, StatusWidgetProvider::class.java))
            ids.forEach { render(context, manager, it) }
        }

        private fun render(context: Context, manager: AppWidgetManager, widgetId: Int) {
            val snapshot = StateStore(context).snapshot()
            val views = RemoteViews(context.packageName, R.layout.widget_status)
            val active = snapshot.phase == Phase.CONNECTED || snapshot.phase == Phase.CONNECTING

            views.setTextViewText(
                R.id.widgetStatus,
                when (snapshot.phase) {
                    Phase.CONNECTED -> context.getString(R.string.status_connected)
                    Phase.CONNECTING -> context.getString(R.string.status_connecting)
                    Phase.ERROR -> context.getString(R.string.status_disconnected)
                    else -> context.getString(R.string.status_disconnected)
                },
            )
            views.setTextViewText(
                R.id.widgetServer,
                snapshot.server?.label ?: context.getString(R.string.fastest_title),
            )
            views.setContentDescription(
                R.id.widgetToggle,
                context.getString(if (active) R.string.widget_disconnect else R.string.widget_connect),
            )
            views.setOnClickPendingIntent(
                R.id.widgetToggle,
                serviceIntent(context, if (active) TunnelService.ACTION_DISCONNECT else TunnelService.ACTION_TOGGLE, 1),
            )
            views.setOnClickPendingIntent(
                R.id.widgetFastest,
                serviceIntent(context, TunnelService.ACTION_CONNECT_FASTEST, 2),
            )
            views.setOnClickPendingIntent(R.id.widgetRoot, openApp(context))
            manager.updateAppWidget(widgetId, views)
        }

        private fun serviceIntent(context: Context, action: String, code: Int): PendingIntent = PendingIntent.getForegroundService(
            context,
            code,
            Intent(context, TunnelService::class.java).setAction(action),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )

        private fun openApp(context: Context): PendingIntent = PendingIntent.getActivity(
            context,
            3,
            Intent(context, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
    }
}

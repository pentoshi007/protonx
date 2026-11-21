package dev.pentoshi.protonx.vpn

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import dev.pentoshi.protonx.R
import dev.pentoshi.protonx.core.Phase
import dev.pentoshi.protonx.ui.MainActivity

object Notifications {
    const val CHANNEL = "connection"
    const val ID = 1001

    fun createChannel(context: Context) {
        val manager = context.getSystemService(NotificationManager::class.java) ?: return
        if (manager.getNotificationChannel(CHANNEL) != null) return
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL, context.getString(R.string.notif_channel), NotificationManager.IMPORTANCE_LOW)
                .apply {
                    setShowBadge(false)
                    enableVibration(false)
                    setSound(null, null)
                },
        )
    }

    fun build(context: Context, phase: Phase, server: String?, error: String?): Notification {
        val title = when (phase) {
            Phase.CONNECTED -> context.getString(R.string.notif_connected, server ?: "ProtonX")
            Phase.CONNECTING -> context.getString(R.string.notif_connecting)
            Phase.ERROR -> error ?: context.getString(R.string.status_disconnected)
            else -> context.getString(R.string.status_disconnected)
        }
        val open = PendingIntent.getActivity(
            context,
            0,
            Intent(context, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val builder = NotificationCompat.Builder(context, CHANNEL)
            .setSmallIcon(R.drawable.ic_shield)
            .setContentTitle(title)
            .setContentText(server ?: context.getString(R.string.app_name))
            .setContentIntent(open)
            .setOngoing(phase == Phase.CONNECTED || phase == Phase.CONNECTING)
            .setOnlyAlertOnce(true)
            .setShowWhen(false)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_DEFERRED)
        if (phase == Phase.CONNECTED) {
            builder.addAction(0, context.getString(R.string.notif_disconnect), disconnectIntent(context))
        }
        return builder.build()
    }

    private fun disconnectIntent(context: Context): PendingIntent = PendingIntent.getForegroundService(
        context,
        1,
        Intent(context, TunnelService::class.java).setAction(TunnelService.ACTION_DISCONNECT),
        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
    )

    fun update(context: Context, phase: Phase, server: String?, error: String?) {
        val manager = context.getSystemService(NotificationManager::class.java) ?: return
        manager.notify(ID, build(context, phase, server, error))
    }

    fun cancel(context: Context) {
        context.getSystemService(NotificationManager::class.java)?.cancel(ID)
    }
}

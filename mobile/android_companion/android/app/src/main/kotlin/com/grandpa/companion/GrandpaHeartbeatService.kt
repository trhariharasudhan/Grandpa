package com.grandpa.companion

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Notification
import android.app.Service
import android.content.Intent
import android.os.Build
import android.os.IBinder

class GrandpaHeartbeatService : Service() {
    override fun onCreate() {
        super.onCreate()
        createChannel()
        val builder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(this, CHANNEL_ID)
        } else {
            @Suppress("DEPRECATION")
            Notification.Builder(this)
        }
        val notification = builder
            .setContentTitle("Grandpa Companion")
            .setContentText("Keeping local LAN companion heartbeat available.")
            .setSmallIcon(android.R.drawable.stat_notify_sync)
            .setOngoing(true)
            .build()
        startForeground(NOTIFICATION_ID, notification)
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun createChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = getSystemService(NotificationManager::class.java)
        val channel = NotificationChannel(
            CHANNEL_ID,
            "Grandpa Companion",
            NotificationManager.IMPORTANCE_LOW,
        )
        channel.description = "Local-only companion heartbeat status"
        manager.createNotificationChannel(channel)
    }

    companion object {
        private const val CHANNEL_ID = "grandpa_companion_heartbeat"
        private const val NOTIFICATION_ID = 4201
    }
}

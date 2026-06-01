package com.grandpa.companion

import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification

class GrandpaNotificationListenerService : NotificationListenerService() {
    override fun onNotificationPosted(sbn: StatusBarNotification) {
        val extras = sbn.notification.extras
        val app = sbn.packageName ?: "Android"
        val title = extras.getCharSequence("android.title")?.toString().orEmpty()
        val text = extras.getCharSequence("android.text")?.toString().orEmpty()
        val kind = when {
            app.contains("dialer", ignoreCase = true) || app.contains("phone", ignoreCase = true) -> "call"
            app.contains("sms", ignoreCase = true) || app.contains("messaging", ignoreCase = true) -> "message"
            else -> "app"
        }
        CompanionBridge.sendNotification(app, title, text, kind)
    }
}

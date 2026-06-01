package com.grandpa.companion

import io.flutter.plugin.common.MethodChannel

object CompanionBridge {
    var channel: MethodChannel? = null

    fun sendNotification(app: String, title: String, summary: String, kind: String) {
        channel?.invokeMethod(
            "notification",
            mapOf(
                "app" to app,
                "title" to redact(title),
                "summary" to redact(summary),
                "kind" to kind,
            ),
        )
    }

    private fun redact(value: String): String {
        val lowered = value.lowercase()
        val sensitive = listOf("password", "otp", "token", "api key", "card", "cvv")
        return if (sensitive.any { lowered.contains(it) }) "[redacted sensitive mobile content]" else value.take(240)
    }
}

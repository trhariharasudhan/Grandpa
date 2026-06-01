package com.grandpa.companion

import android.app.Service
import android.content.Intent
import android.os.IBinder

class GrandpaHeartbeatService : Service() {
    override fun onBind(intent: Intent?): IBinder? = null
}

package com.fashionstore.mobile

import android.app.NotificationChannel
import android.app.NotificationManager
import android.os.Build
import android.os.Bundle
import io.flutter.embedding.android.FlutterActivity

class MainActivity : FlutterActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        crearCanalDeAvisos()
    }

    /// Canal de los avisos push (mismo id que manda el servidor): con importancia alta salen como aviso emergente.
    private fun crearCanalDeAvisos() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val canal = NotificationChannel(
            "fashionstore_avisos",
            "Avisos de FashionStore",
            NotificationManager.IMPORTANCE_HIGH,
        )
        canal.description = "Pedidos, reservas y envíos"
        getSystemService(NotificationManager::class.java)?.createNotificationChannel(canal)
    }
}

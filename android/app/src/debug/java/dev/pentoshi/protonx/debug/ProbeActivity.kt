package dev.pentoshi.protonx.debug

import android.os.Bundle
import android.util.Log
import androidx.appcompat.app.AppCompatActivity
import dev.pentoshi.protonx.core.HttpRequest
import dev.pentoshi.protonx.core.UrlConnectionTransport
import dev.pentoshi.protonx.net.FlowProbe

/** Debug builds only: proves the tunnel carries real traffic from the app process. */
class ProbeActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Thread {
            val dns = FlowProbe.reachesInternet()
            val result = runCatching {
                UrlConnectionTransport().execute(
                    HttpRequest("GET", "https://proton.me", mapOf("User-Agent" to "ProtonX-probe"), null),
                )
            }
            val line = result.fold(
                onSuccess = { response -> "dns=$dns http=${response.status} bytes=${response.body.length}" },
                onFailure = { "dns=$dns http=failed error=${it.javaClass.simpleName}: ${it.message}" },
            )
            Log.i(TAG, line)
            runOnUiThread { finish() }
        }.start()
    }

    private companion object {
        const val TAG = "ProtonXDebug"
    }
}

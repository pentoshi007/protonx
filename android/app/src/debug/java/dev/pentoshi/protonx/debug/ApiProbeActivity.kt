package dev.pentoshi.protonx.debug

import android.os.Bundle
import android.util.Log
import androidx.appcompat.app.AppCompatActivity
import dev.pentoshi.protonx.core.ProtonApi
import dev.pentoshi.protonx.data.StateStore

/** Debug builds only: exercises the real Proton API and logs the outcome. */
class ApiProbeActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Thread {
            val store = StateStore(this)
            val api = ProtonApi(
                sessionProvider = { store.session() },
                sessionSaver = { store.saveSession(it) },
            )
            val line = runCatching { api.logicals() }.fold(
                onSuccess = { payload ->
                    "logicals ok count=${payload.optJSONArray("LogicalServers")?.length() ?: -1}"
                },
                onFailure = { "logicals failed ${it.javaClass.simpleName}: ${it.message}" },
            )
            Log.i(TAG, line)
            runOnUiThread { finish() }
        }.start()
    }

    private companion object {
        const val TAG = "ProtonXDebug"
    }
}

package dev.pentoshi.protonx.debug

import android.os.Bundle
import android.util.Log
import androidx.appcompat.app.AppCompatActivity
import dev.pentoshi.protonx.core.Session
import dev.pentoshi.protonx.data.StateStore
import org.json.JSONObject
import java.io.File

/**
 * Debug builds only: imports a session JSON that was pushed to the device, so an
 * emulator run can be tested without typing credentials. The release variant has
 * no such component. Tokens are never logged.
 */
class SessionImportActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val path = intent.getStringExtra(EXTRA_PATH)
            ?: File(getExternalFilesDir(null), "protonx-session.json").absolutePath
        val raw = runCatching { File(path).readText() }.getOrNull()
        if (raw == null) return finishWith("cannot read $path")
        val json = runCatching { JSONObject(raw) }.getOrNull()
            ?: return finishWith("invalid json in $path")
        val session = Session(
            userId = json.optString("userId"),
            accessToken = json.optString("accessToken"),
            refreshToken = json.optString("refreshToken"),
            username = json.optString("username"),
        )
        if (session.accessToken.isBlank()) return finishWith("session has no access token")
        StateStore(this).saveSession(session)
        finishWith("imported ${session.username} access=${session.accessToken.length} refresh=${session.refreshToken.length}")
    }

    private fun finishWith(message: String) {
        Log.i(TAG, message)
        finish()
    }

    private companion object {
        const val TAG = "ProtonXDebug"
        const val EXTRA_PATH = "path"
    }
}

package dev.pentoshi.protonx.ui

import android.content.Intent
import android.content.res.Configuration
import android.net.VpnService
import android.os.Bundle
import android.view.View
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import dev.pentoshi.protonx.R

/** Android asks for VPN consent once; every connect path shares this prompt. */
abstract class ConsentActivity : AppCompatActivity() {
    private var pending: (() -> Unit)? = null

    private val launcher = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        val action = pending
        pending = null
        if (result.resultCode == RESULT_OK && action != null) action() else onConsentDenied()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        val night = resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK ==
            Configuration.UI_MODE_NIGHT_YES
        WindowInsetsControllerCompat(window, window.decorView).apply {
            isAppearanceLightStatusBars = !night
            isAppearanceLightNavigationBars = !night
        }
    }

    protected fun withConsent(block: () -> Unit) {
        val request: Intent? = VpnService.prepare(this)
        if (request == null) block() else {
            pending = block
            launcher.launch(request)
        }
    }

    /** Content is drawn edge to edge on API 35, so the system bars become padding. */
    protected fun applyInsets(root: View) {
        ViewCompat.setOnApplyWindowInsetsListener(root) { view, insets ->
            val bars = insets.getInsets(
                WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout(),
            )
            view.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            insets
        }
    }

    protected open fun onConsentDenied() {
        Toast.makeText(this, R.string.vpn_permission_body, Toast.LENGTH_LONG).show()
    }
}

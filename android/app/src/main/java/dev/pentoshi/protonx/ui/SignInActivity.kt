package dev.pentoshi.protonx.ui

import android.os.Bundle
import android.view.View
import android.view.inputmethod.EditorInfo
import androidx.lifecycle.lifecycleScope
import dev.pentoshi.protonx.ProtonXApp
import dev.pentoshi.protonx.R
import dev.pentoshi.protonx.core.Session
import dev.pentoshi.protonx.core.SignInOutcome
import dev.pentoshi.protonx.databinding.ActivitySignInBinding
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class SignInActivity : ConsentActivity() {
    private lateinit var binding: ActivitySignInBinding
    private val tunnel by lazy { ProtonXApp.of(this).tunnel }
    private var pending: Session? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivitySignInBinding.inflate(layoutInflater)
        setContentView(binding.root)
        applyInsets(binding.root)
        binding.signInButton.setOnClickListener { submit() }
        binding.passwordInput.setOnEditorActionListener { _, actionId, _ ->
            if (actionId == EditorInfo.IME_ACTION_DONE) submit()
            true
        }
        binding.codeInput.setOnEditorActionListener { _, actionId, _ ->
            if (actionId == EditorInfo.IME_ACTION_DONE) submit()
            true
        }
    }

    private fun submit() {
        val code = binding.codeInput.text?.toString()?.trim().orEmpty()
        val waiting = pending
        if (waiting != null) return finishTwoFactor(waiting, code)

        val username = binding.usernameInput.text?.toString()?.trim().orEmpty()
        val password = binding.passwordInput.text?.toString().orEmpty()
        if (username.isEmpty() || password.isEmpty()) {
            return showError(getString(R.string.sign_in_missing))
        }
        busy(true)
        lifecycleScope.launch {
            runCatching { withContext(Dispatchers.IO) { tunnel.signIn(username, password) } }
                .onSuccess { outcome ->
                    busy(false)
                    when (outcome) {
                        is SignInOutcome.SignedIn -> finish()
                        is SignInOutcome.NeedsCode -> askForCode(outcome.session)
                    }
                }
                .onFailure { error ->
                    busy(false)
                    showError(error.message ?: getString(R.string.sign_in_failed))
                }
        }
    }

    private fun askForCode(session: Session) {
        pending = session
        binding.codeBox.visibility = View.VISIBLE
        binding.passwordBox.visibility = View.GONE
        binding.usernameBox.visibility = View.GONE
        binding.signInSubtitle.setText(R.string.sign_in_2fa)
        binding.signInButton.setText(R.string.sign_in_verify)
        binding.codeInput.requestFocus()
    }

    private fun finishTwoFactor(session: Session, code: String) {
        if (code.isEmpty()) return showError(getString(R.string.sign_in_code_missing))
        busy(true)
        lifecycleScope.launch {
            runCatching { withContext(Dispatchers.IO) { tunnel.finishTwoFactor(session, code) } }
                .onSuccess { busy(false); finish() }
                .onFailure { error -> busy(false); showError(error.message ?: getString(R.string.sign_in_failed)) }
        }
    }

    private fun busy(working: Boolean) {
        binding.signInProgress.visibility = if (working) View.VISIBLE else View.GONE
        binding.signInButton.isEnabled = !working
        binding.signInButton.setText(
            when {
                working -> R.string.sign_in_working
                pending != null -> R.string.sign_in_verify
                else -> R.string.sign_in_action
            },
        )
    }

    private fun showError(message: String) {
        binding.signInError.text = message
        binding.signInError.visibility = View.VISIBLE
    }
}

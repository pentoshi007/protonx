package dev.pentoshi.protonx.ui

import android.animation.ValueAnimator
import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.RectF
import android.util.AttributeSet
import android.view.animation.LinearInterpolator
import android.widget.FrameLayout
import androidx.core.content.ContextCompat
import dev.pentoshi.protonx.R
import dev.pentoshi.protonx.core.Phase

/**
 * The signature element: a ring that *is* the connection state. It sweeps while
 * connecting, locks solid when traffic is proven, and turns red on failure.
 */
class StatusRingView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0,
) : FrameLayout(context, attrs, defStyleAttr) {

    private val density = resources.displayMetrics.density
    private val ring = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = 3f * density
        strokeCap = Paint.Cap.ROUND
    }
    private val track = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = 3f * density
        color = ContextCompat.getColor(context, R.color.ring_track)
    }
    private var phase = Phase.IDLE
    private var sweepStart = -90f
    private var animator: ValueAnimator? = null

    init {
        setWillNotDraw(false)
    }

    fun setPhase(next: Phase) {
        if (phase == next) return
        phase = next
        animateSweep()
        invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val radius = (minOf(width, height) - 3f * density) / 2f
        val centerX = width / 2f
        val centerY = height / 2f
        canvas.drawCircle(centerX, centerY, radius, track)
        val box = RectF(centerX - radius, centerY - radius, centerX + radius, centerY + radius)
        when (phase) {
            Phase.CONNECTED -> arc(canvas, box, 360f, R.color.success)
            Phase.CONNECTING -> arc(canvas, box, 84f, R.color.brand, sweepStart)
            Phase.ERROR -> arc(canvas, box, 360f, R.color.danger)
            else -> Unit
        }
    }

    private fun arc(canvas: Canvas, box: RectF, sweep: Float, colorRes: Int, start: Float = -90f) {
        ring.color = ContextCompat.getColor(context, colorRes)
        canvas.drawArc(box, start, sweep, false, ring)
    }

    private fun animateSweep() {
        animator?.cancel()
        animator = null
        if (phase != Phase.CONNECTING || !ValueAnimator.areAnimatorsEnabled()) {
            sweepStart = -90f
            return
        }
        animator = ValueAnimator.ofFloat(-90f, 270f).apply {
            duration = 1_400
            repeatCount = ValueAnimator.INFINITE
            interpolator = LinearInterpolator()
            addUpdateListener { update ->
                sweepStart = update.animatedValue as Float
                invalidate()
            }
            start()
        }
    }

    override fun onDetachedFromWindow() {
        animator?.cancel()
        animator = null
        super.onDetachedFromWindow()
    }
}

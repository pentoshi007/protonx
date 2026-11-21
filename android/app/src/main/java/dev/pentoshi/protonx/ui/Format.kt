package dev.pentoshi.protonx.ui

import java.util.Locale

fun bytesLabel(value: Long): String = when {
    value >= 1_000_000 -> String.format(Locale.US, "%.1f MB", value / 1_000_000.0)
    value >= 1_000 -> String.format(Locale.US, "%.0f KB", value / 1_000.0)
    else -> "$value B"
}

fun durationLabel(millis: Long): String {
    val totalSeconds = (millis / 1000).coerceAtLeast(0)
    return String.format(Locale.US, "%02d:%02d", totalSeconds / 60, totalSeconds % 60)
}

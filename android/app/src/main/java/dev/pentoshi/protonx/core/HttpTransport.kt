package dev.pentoshi.protonx.core

import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

class HttpRequest(
    val method: String,
    val url: String,
    val headers: Map<String, String>,
    val body: ByteArray?,
)

class HttpResponse(val status: Int, val body: String)

fun interface Transport {
    fun execute(request: HttpRequest): HttpResponse
}

/** Zero-dependency HTTP so the app ships without OkHttp's code and thread pools. */
class UrlConnectionTransport : Transport {
    override fun execute(request: HttpRequest): HttpResponse {
        val connection = (URL(request.url).openConnection() as HttpURLConnection).apply {
            requestMethod = request.method
            connectTimeout = CONNECT_TIMEOUT_MS
            readTimeout = READ_TIMEOUT_MS
            instanceFollowRedirects = false
            useCaches = false
            request.headers.forEach { (name, value) -> setRequestProperty(name, value) }
            if (request.body != null) {
                doOutput = true
                setFixedLengthStreamingMode(request.body.size)
            }
        }
        try {
            request.body?.let { connection.outputStream.use { stream -> stream.write(it) } }
            val status = connection.responseCode
            val stream = if (status >= 400) connection.errorStream else connection.inputStream
            val body = stream?.bufferedReader()?.use { it.readText() } ?: ""
            return HttpResponse(status, body)
        } finally {
            connection.disconnect()
        }
    }

    private companion object {
        const val CONNECT_TIMEOUT_MS = 15_000
        const val READ_TIMEOUT_MS = 25_000
    }
}

fun encodeQuery(params: Map<String, String>): String =
    params.entries.joinToString("&") { (key, value) ->
        "${URLEncoder.encode(key, "UTF-8")}=${URLEncoder.encode(value, "UTF-8")}"
    }

@Throws(IOException::class)
fun buildUrl(base: String, path: String, params: Map<String, String>): String {
    if (params.isEmpty()) return base + path
    val separator = if ('?' in path) '&' else '?'
    return base + path + separator + encodeQuery(params)
}

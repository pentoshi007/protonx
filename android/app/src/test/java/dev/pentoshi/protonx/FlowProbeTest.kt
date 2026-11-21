package dev.pentoshi.protonx

import dev.pentoshi.protonx.net.FlowProbe
import org.junit.Assert.assertEquals
import org.junit.Test

class FlowProbeTest {
    @Test
    fun buildsAMinimalDnsQueryForTheProbeName() {
        val query = FlowProbe.query("proton.me", 0x1234)
        val expected = byteArrayOf(
            0x12, 0x34, 0x01, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x06, 'p'.code.toByte(), 'r'.code.toByte(), 'o'.code.toByte(), 't'.code.toByte(), 'o'.code.toByte(), 'n'.code.toByte(),
            0x02, 'm'.code.toByte(), 'e'.code.toByte(),
            0x00, 0x00, 0x01, 0x00, 0x01,
        )
        assertEquals(expected.toList(), query.toList())
    }

    @Test
    fun aDeadResolverIsReportedAsNoTraffic() {
        assertEquals(false, FlowProbe.reachesInternet(resolver = "127.0.0.1", timeoutMs = 200))
    }
}

package dev.pentoshi.protonx

import dev.pentoshi.protonx.core.Entry
import dev.pentoshi.protonx.core.Logical
import dev.pentoshi.protonx.core.Selection
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class SelectionTest {
    private val key = "a".repeat(43) + "="

    private fun server(
        name: String,
        country: String,
        load: Int,
        tier: Int = 0,
        status: Int = 1,
        features: Int = 0,
        entryCountry: String = country,
        withKey: Boolean = true,
    ) = Logical(
        id = name,
        name = name,
        exitCountry = country,
        entryCountry = entryCountry,
        city = "City",
        tier = tier,
        load = load,
        status = status,
        features = features,
        entries = listOf(Entry("id", name, "$name.example", "1.2.3.4", if (withKey) key else "", listOf(51820))),
    )

    private val pool = listOf(
        server("NL-FREE#1", "NL", 80),
        server("NL-FREE#2", "NL", 20),
        server("US-FREE#1", "US", 35),
        server("US-PLUS#1", "US", 5, tier = 2),
        server("SE-FREE#1", "SE", 1, status = 0),
        server("CH-FREE#1", "CH", 2, entryCountry = "IS"),
        server("DE-FREE#1", "DE", 3, withKey = false),
        server("JP-PLUS#1", "JP", 4, tier = 2, features = 4),
    )

    @Test
    fun onlyFreeOnlineStandardWireGuardServersAreEligible() {
        val names = Selection.eligible(pool).map { it.displayName() }
        assertEquals(listOf("NL-FREE#1", "NL-FREE#2", "US-FREE#1"), names)
    }

    @Test
    fun paidServersAreAvailableWhenAsked() {
        val names = Selection.eligible(pool, includePaid = true).map { it.displayName() }
        assertEquals(listOf("NL-FREE#1", "NL-FREE#2", "US-FREE#1", "US-PLUS#1"), names)
    }

    @Test
    fun fastestIsTheLowestLoad() {
        assertEquals("NL-FREE#2", Selection.fastest(pool)?.displayName())
    }

    @Test
    fun countriesCountOnlyEligibleServers() {
        val rows = Selection.countries(pool)
        assertEquals(listOf("NL", "US"), rows.map { it.code })
        assertEquals(2, rows.first { it.code == "NL" }.servers)
        assertEquals(20, rows.first { it.code == "NL" }.bestLoad)
        assertEquals("Netherlands", rows.first { it.code == "NL" }.name)
    }

    @Test
    fun serversInACountryAreSortedByLoad() {
        assertEquals(listOf("NL-FREE#2", "NL-FREE#1"), Selection.serversIn(pool, "NL").map { it.displayName() })
    }

    @Test
    fun serverNamesResolveExactlyAndByFragment() {
        assertEquals("US-FREE#1", Selection.byName(pool, "US-FREE#1")?.displayName())
        assertEquals("US-FREE#1", Selection.byName(pool, "us-free", country = "US")?.displayName())
        assertNull(Selection.byName(pool, "DE-FREE#1"))
    }
}

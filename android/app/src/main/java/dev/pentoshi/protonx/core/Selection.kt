package dev.pentoshi.protonx.core

data class CountryRow(
    val code: String,
    val name: String,
    val servers: Int,
    val bestLoad: Int,
)

object Selection {

    fun eligible(
        pool: List<Logical>,
        includePaid: Boolean = false,
        country: String? = null,
    ): List<Logical> =
        pool.filter { server ->
            server.online && !server.secureCore && server.wireguardEntries.isNotEmpty() &&
                (includePaid || server.free) && (country == null || server.exitCountry == country)
        }

    fun countries(pool: List<Logical>, includePaid: Boolean = false): List<CountryRow> {
        val rows = eligible(pool, includePaid)
            .groupBy { it.exitCountry }
            .map { (code, servers) ->
                CountryRow(
                    code = code,
                    name = CountryNames.of(code),
                    servers = servers.size,
                    bestLoad = servers.minOf { it.load },
                )
            }
        return rows.sortedBy { it.name }
    }

    fun serversIn(pool: List<Logical>, country: String, includePaid: Boolean = false): List<Logical> =
        eligible(pool, includePaid, country).sortedWith(compareBy({ it.load }, { it.displayName() }))

    fun fastest(pool: List<Logical>, includePaid: Boolean = false): Logical? =
        eligible(pool, includePaid).minWithOrNull(compareBy({ it.load }, { it.displayName() }))

    fun byName(
        pool: List<Logical>,
        name: String,
        country: String? = null,
        includePaid: Boolean = false,
    ): Logical? {
        val candidates = eligible(pool, includePaid, country)
        val lowered = name.trim().lowercase()
        return candidates.firstOrNull { it.displayName().lowercase() == lowered }
            ?: candidates.filter { it.displayName().lowercase().contains(lowered) }.singleOrNull()
    }
}

import random

from .countries import NAMES
from .errors import SelectionError
from .logicals import LogicalList

FASTEST = "fastest"
RANDOM = "random"


def _available(logicals):
    return logicals.countries()


def resolve_country(logicals, query):
    if not query:
        return None
    lowered = query.strip().lower()
    if lowered in (FASTEST, RANDOM):
        return lowered
    available = _available(logicals)
    if query.strip().upper() in available:
        return query.strip().upper()
    exact = [code for code, label in NAMES.items() if label.lower() == lowered and code in available]
    if len(exact) == 1:
        return exact[0]
    partial = [code for code, label in NAMES.items() if lowered in label.lower() and code in available]
    if len(partial) == 1:
        return partial[0]
    if partial:
        options = ", ".join(sorted(f"{code} ({NAMES[code]})" for code in partial))
        raise SelectionError(f"ambiguous country '{query}', matches: {options}")
    raise SelectionError(f"unknown country '{query}'. Run 'protonx countries' to list them.")


def eligible(logicals, country=None, include_paid=False, p2p_only=False):
    pool = LogicalList(logicals).online_only().standard_only()
    if country and country not in (FASTEST, RANDOM):
        pool = pool.by_country(country)
    if not include_paid:
        pool = pool.free_only()
    if p2p_only:
        pool = LogicalList(item for item in pool if item.p2p)
    return LogicalList(item for item in pool if item.wireguard_entries)


def candidates(logicals, country=None, include_paid=False, p2p_only=False):
    pool = eligible(logicals, country, include_paid, p2p_only)
    if not pool:
        scope = country or "any location"
        tier = "any-tier" if include_paid else "free-tier"
        raise SelectionError(
            f"no online {tier} WireGuard server for {scope}. Try '--paid' or 'protonx countries'."
        )
    return pool


def by_name(pool, name):
    lowered = name.strip().lower()
    exact = [item for item in pool if item.name.lower() == lowered]
    if exact:
        return exact[0]
    partial = [item for item in pool if lowered in item.name.lower()]
    if len(partial) == 1:
        return partial[0]
    if partial:
        options = ", ".join(sorted(item.name for item in partial)[:8])
        raise SelectionError(f"server '{name}' is ambiguous, matches: {options}")
    raise SelectionError(f"no server named '{name}' in the selected location.")


def fastest(pool):
    return sorted(pool, key=lambda item: (item.load, item.name))[0]


def select(logicals, country=None, server=None, include_paid=False, p2p_only=False, strategy=FASTEST):
    pool = candidates(logicals, country, include_paid, p2p_only)
    if server:
        return by_name(pool, server)
    if strategy == RANDOM or country == RANDOM:
        return random.choice(list(pool))
    return fastest(pool)

"""ULID generation for rows that may be created without a server.

A local-first client creates projects and bookings while offline, so it cannot
wait for SQLite to hand out a primary key. Every synchronised row therefore
carries a second identifier minted by whoever created it - the browser or the
server - and this is where the server's half comes from.

ULID rather than UUID4 because the first 48 bits are a millisecond timestamp:
identifiers sort by creation time, which keeps index inserts local and makes a
raw table dump readable. 80 random bits are far more than this application will
ever need to avoid a collision between two of its own devices.

No dependency: the whole format is a base32 alphabet and a shift loop, and the
browser needs its own implementation in TypeScript regardless.
"""

import secrets
import time

# Crockford's base32 - the digits and uppercase letters, minus I, L, O and U,
# so a ULID read aloud or copied by hand cannot turn into a different one.
CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

ULID_LENGTH = 26


def new_ulid():
    """Return a fresh 26-character ULID: 48 bits of time, 80 of randomness."""
    value = (int(time.time() * 1000) << 80) | secrets.randbits(80)

    characters = []
    for _ in range(ULID_LENGTH):
        characters.append(CROCKFORD_ALPHABET[value & 0x1F])
        value >>= 5

    return "".join(reversed(characters))

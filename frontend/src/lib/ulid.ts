/**
 * ULID, the browser half of app/ulid.py.
 *
 * A row created here has to be able to name itself: there is no server to hand
 * out a key, and two devices inventing the same number would silently merge two
 * different projects into one.
 */

// Crockford's base32 - no I, L, O or U, so a ULID read aloud or copied by hand
// cannot turn into a different one. Identical to the Python alphabet.
const ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";

export const ULID_LENGTH = 26;

export function newUlid(now: number = Date.now()): string {
  const random = new Uint8Array(10);
  crypto.getRandomValues(random);

  // 48 bits of milliseconds, then 80 random, as one big integer - the same
  // layout Python builds, so identifiers from either side sort together.
  let value = BigInt(Math.trunc(now)) << 80n;
  for (const byte of random) {
    value = (value << 8n) | BigInt(byte);
  }

  let text = "";
  for (let index = 0; index < ULID_LENGTH; index += 1) {
    text = ALPHABET[Number(value & 31n)] + text;
    value >>= 5n;
  }
  return text;
}

/** Getting from "a page loaded" to "there is a local copy to read from". */

import {
  openDatabase,
  readMeta,
  writeMeta,
  type LocalDatabase,
} from "./db/schema";
import { pull, type PullResult } from "./sync/engine";
import type { Me } from "./sync/types";

const IDENTITY_KEY = "identity";
/** Where to look for the account when the network cannot say. */
const LAST_ACCOUNT_KEY = "productivity:last-account";

export interface Session {
  me: Me;
  database: LocalDatabase;
  /** True when the server could not be reached and this came from the copy. */
  offline: boolean;
}

export interface Started {
  session: Session;
  pulled: PullResult | null;
}

class SignedOut extends Error {}

async function askServer(): Promise<Me> {
  const response = await fetch("/api/me", {
    headers: { "X-Requested-With": "XMLHttpRequest", Accept: "application/json" },
    credentials: "same-origin",
  });

  if (response.status === 401) throw new SignedOut();
  if (!response.ok) throw new Error(`/api/me answered ${response.status}`);

  return (await response.json()) as Me;
}

export async function start(): Promise<Started> {
  let me: Me | null = null;
  let offline = false;

  try {
    me = await askServer();
  } catch (error) {
    if (error instanceof SignedOut) {
      // Signing in stays a server-rendered page: there is nothing to show
      // before a session exists, and a password has no reason to pass here.
      window.location.href = "/auth/login";
      throw error;
    }
    // Anything else is the network being absent, which is not an error in an
    // application whose data is already on this device.
    offline = true;
  }

  const account = me?.user.email ?? localStorage.getItem(LAST_ACCOUNT_KEY);
  if (!account) {
    // Offline and this browser has never signed in - there is genuinely
    // nothing to show.
    throw new Error("No local copy on this device yet. Connect once to set it up.");
  }

  const database = openDatabase(account);

  if (me) {
    localStorage.setItem(LAST_ACCOUNT_KEY, me.user.email);
    await writeMeta(database, IDENTITY_KEY, me);

    // From here on the copy holds changes that have not reached the server, so
    // eviction would be data loss rather than a cold cache.
    if (navigator.storage?.persist) {
      await navigator.storage.persist().catch(() => undefined);
    }
  } else {
    me = await readMeta<Me | null>(database, IDENTITY_KEY, null);
    if (!me) throw new Error("No local copy on this device yet. Connect once to set it up.");
  }

  const pulled = offline ? null : await pull(database);
  return { session: { me, database, offline }, pulled };
}

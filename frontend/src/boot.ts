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

export class SignedOut extends Error {}

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
      // Handed back to the caller, which shows the sign-in view inside the
      // application. Leaving for a server-rendered page would drop out of the
      // shell, which in an installed PWA is a visible seam.
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


/**
 * Sign out, and take the local copy with it.
 *
 * This is new, and it is the one thing local-first genuinely adds to signing
 * out: the data is no longer only in a cookie's reach, it is on the disk of
 * this browser. Leaving it behind would show the next person at this machine
 * everything the last one was working on.
 */
export async function signOut(database: LocalDatabase): Promise<void> {
  const name = database.name;

  try {
    await fetch("/api/auth/logout", {
      method: "POST",
      headers: {
        "X-Requested-With": "XMLHttpRequest",
        "X-CSRF-Token": document.cookie.match(/(?:^|;\s*)csrf_token=([^;]*)/)?.[1] ?? "",
      },
      credentials: "same-origin",
    });
  } catch {
    // No network: the session cookie outlives this, but the copy below does not.
  }

  database.close();
  await new Promise<void>((resolve) => {
    // Bounded on purpose. A live query in another tab holds the database open,
    // and deleteDatabase then waits for it - which would leave the person
    // staring at a page that says nothing while apparently still signed in.
    // The reload below closes this tab's connections either way, so a delete
    // that has not finished yet finishes then.
    const giveUp = setTimeout(resolve, 1500);
    const done = () => {
      clearTimeout(giveUp);
      resolve();
    };

    const request = indexedDB.deleteDatabase(name);
    request.onsuccess = done;
    request.onerror = done;
    request.onblocked = done;
  });

  try {
    localStorage.removeItem(LAST_ACCOUNT_KEY);
  } catch {
    // Nothing to clean up if storage was never available.
  }

  window.location.reload();
}

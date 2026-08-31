/**
 * What the synchronisation button knows.
 *
 * Synchronising runs on its own when there is a network, but it is never
 * invisible: this is the one place that says what is waiting, what went wrong
 * and when the server was last heard from.
 */

import type { LocalDatabase, OutboxEntry } from "../db/schema";
import { LAST_SYNC_KEY, readMeta } from "../db/schema";
import { push, pull } from "./engine";

export type SyncPhase = "idle" | "working" | "offline" | "error";

/** How often to look, when nothing else prompts it. */
const HEARTBEAT_MS = 60_000;

class SyncState {
  phase = $state<SyncPhase>("idle");
  pending = $state<OutboxEntry[]>([]);
  conflicts = $state(0);
  lastSync = $state<string | null>(null);
  message = $state("");

  #database: LocalDatabase | null = null;
  #timer: ReturnType<typeof setInterval> | null = null;
  #running = false;

  get pendingCount(): number {
    return this.pending.length;
  }

  /** One line for the button itself. */
  get label(): string {
    if (this.phase === "working") return "Syncing…";
    if (this.conflicts > 0) {
      return this.conflicts === 1 ? "1 conflict" : `${this.conflicts} conflicts`;
    }
    if (this.phase === "offline") {
      return this.pendingCount > 0
        ? `Offline — ${this.pendingCount} waiting`
        : "Offline";
    }
    if (this.pendingCount > 0) {
      return this.pendingCount === 1 ? "1 change waiting" : `${this.pendingCount} changes waiting`;
    }
    return "Synced";
  }

  async attach(database: LocalDatabase): Promise<void> {
    this.#database = database;
    await this.refresh();

    // Automatic, but never silent: every path below ends up changing what the
    // button says.
    window.addEventListener("online", () => void this.run());
    window.addEventListener("offline", () => {
      this.phase = "offline";
    });
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") void this.run();
    });
    this.#timer = setInterval(() => void this.run(), HEARTBEAT_MS);
  }

  detach(): void {
    if (this.#timer !== null) clearInterval(this.#timer);
    this.#timer = null;
  }

  async refresh(): Promise<void> {
    if (!this.#database) return;
    this.pending = await this.#database.outbox.orderBy("changed_at").reverse().toArray();
    this.conflicts = await this.#database.conflicts.count();
    this.lastSync = await readMeta<string | null>(this.#database, LAST_SYNC_KEY, null);
  }

  /** Pull then push. Safe to call from anywhere; overlapping calls collapse. */
  async run(): Promise<void> {
    if (!this.#database || this.#running) return;
    if (!navigator.onLine) {
      this.phase = "offline";
      await this.refresh();
      return;
    }

    this.#running = true;
    this.phase = "working";
    this.message = "";

    try {
      await pull(this.#database);
      const pushed = await push(this.#database);
      this.phase = "idle";
      if (pushed.refused) this.message = pushed.refused;
    } catch (error) {
      // Being offline is not a failure in an application whose data is here.
      this.phase = navigator.onLine ? "error" : "offline";
      this.message = error instanceof Error ? error.message : String(error);
    } finally {
      this.#running = false;
      await this.refresh();
    }
  }
}

export const sync = new SyncState();

/** Turn one queued operation into something a person can read. */
export function describe(entry: OutboxEntry, titleOf: (uid: string) => string): string {
  const noun = {
    project: "project",
    day_slot: "booking",
    timeline_item: "timeline card",
    timeline_group: "timeline column",
    time_entry: "time session",
  }[entry.entity];

  const name = titleOf(entry.uid);
  const subject = name ? `${noun} ${name}` : noun;

  if (entry.op === "create") return `Added ${subject}`;
  if (entry.op === "delete") return `Deleted ${subject}`;

  const fields = Object.keys(entry.fields);
  if (fields.length === 1 && fields[0] === "is_done") {
    return entry.fields.is_done ? `Ticked off ${subject}` : `Un-ticked ${subject}`;
  }
  if (fields.length === 1 && fields[0] === "long_goal") return `Edited the plan of ${subject}`;
  return `Changed ${subject}`;
}

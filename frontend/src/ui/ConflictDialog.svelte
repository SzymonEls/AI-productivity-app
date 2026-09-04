<script lang="ts">
  /**
   * The same thing changed in two places. One at a time, both sides shown,
   * and the person decides - the rule the whole design turns on.
   */
  import type { ConflictEntry, LocalDatabase } from "../db/schema";
  import { dismissable } from "../lib/dismiss";
  import { live } from "../lib/live.svelte";
  import { canKeepBoth, differences, keepBoth, keepMine, keepServer } from "../sync/resolve";
  import { sync } from "../sync/store.svelte";

  let { database, onclose }: { database: LocalDatabase; onclose: () => void } = $props();

  const conflicts = live(() => database.conflicts.toArray(), []);
  const current = $derived(conflicts.value[0] ?? null);

  const noun: Record<string, string> = {
    project: "project",
    day_slot: "booking",
    timeline_item: "timeline card",
    timeline_group: "timeline column",
    time_entry: "time session",
  };

  const explanation: Record<string, string> = {
    stale: "This changed somewhere else after you last saw it.",
    slot_taken: "Another device booked this slot first.",
    gone: "This was deleted somewhere else.",
    already_exists: "Something with this identity already reached the server.",
    missing_uid: "This change arrived without an identity and cannot be applied.",
  };

  function show(value: unknown): string {
    if (value === null || value === undefined || value === "") return "—";
    if (typeof value === "boolean") return value ? "yes" : "no";
    const text = String(value);
    return text.length > 400 ? `${text.slice(0, 400)}…` : text;
  }

  async function settle(action: (db: LocalDatabase, c: ConflictEntry) => Promise<void>) {
    if (!current) return;
    await action(database, current);
    await sync.refresh();
    void sync.run();
    if (conflicts.value.length <= 1) onclose();
  }
</script>

<div class="overlay" role="dialog" aria-modal="true" aria-label="Resolve a conflict" use:dismissable={onclose}>
  <div class="panel">
    {#if !current}
      <p>Nothing left to settle.</p>
      <button type="button" class="btn" onclick={onclose}>Close</button>
    {:else}
      <header>
        <div>
          <strong>{noun[current.entity] ?? current.entity} changed twice</strong>
          <p class="muted">{explanation[current.reason] ?? current.reason}</p>
        </div>
        <span class="muted">{conflicts.value.length} to settle</span>
      </header>

      <table class="sides">
        <thead>
          <tr><th></th><th>Yours</th><th>On the server</th></tr>
        </thead>
        <tbody>
          {#each differences(current) as row (row.field)}
            <tr>
              <th scope="row">{row.field.replace(/_/g, " ")}</th>
              <td><pre>{show(row.mine)}</pre></td>
              <td><pre>{show(row.theirs)}</pre></td>
            </tr>
          {/each}
        </tbody>
      </table>

      <div class="choices">
        <button type="button" class="btn" onclick={() => settle(keepMine)}>Keep mine</button>
        <button type="button" class="btn ghost" onclick={() => settle(keepServer)}>
          Keep the server's
        </button>
        {#if canKeepBoth(current)}
          <button type="button" class="btn ghost" onclick={() => settle(keepBoth)}>
            Keep both
          </button>
        {/if}
        <button type="button" class="linkish" onclick={onclose}>Later</button>
      </div>
    {/if}
  </div>
</div>

<style>
  .overlay { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.4); display: grid; place-items: center; padding: 1rem; z-index: 100; }
  .panel { background: var(--app-surface, Canvas); border-radius: 0.9rem; padding: 1.1rem; width: min(44rem, 100%); max-height: 85vh; overflow: auto; }
  header { display: flex; justify-content: space-between; gap: 1rem; align-items: flex-start; margin-bottom: 0.9rem; }
  header p { margin: 0.15rem 0 0; font-size: 0.88rem; }
  .muted { opacity: 0.65; font-size: 0.85rem; }
  .sides { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
  .sides th { text-align: left; font-weight: 600; opacity: 0.6; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.05em; padding: 0.35rem 0.5rem 0.35rem 0; vertical-align: top; }
  .sides td { padding: 0.35rem 0.5rem; border-top: 1px solid rgba(127, 127, 127, 0.15); vertical-align: top; width: 42%; }
  .sides pre { margin: 0; white-space: pre-wrap; word-break: break-word; font: inherit; }
  .choices { display: flex; flex-wrap: wrap; gap: 0.6rem; align-items: center; margin-top: 1.1rem; }
  .btn { border: 1px solid rgba(127, 127, 127, 0.35); background: var(--bs-primary, #4f46e5); color: #fff; border-radius: 0.5rem; padding: 0.4rem 0.9rem; cursor: pointer; }
  .btn.ghost { background: transparent; color: inherit; }
  .linkish { background: none; border: 0; color: inherit; text-decoration: underline; cursor: pointer; font: inherit; opacity: 0.7; }
</style>

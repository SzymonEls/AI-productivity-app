<script lang="ts">
  /**
   * Days already gone.
   *
   * A record, so nothing here can be booked, moved or freed - but the tick
   * still works, because a session finished on Tuesday can be ticked off on
   * Thursday and still counts towards the health ring.
   */
  import { updateRow } from "../db/mutate";
  import type { LocalDatabase } from "../db/schema";
  import {
    ARCHIVE_WEEKS,
    SLOTS,
    addDays,
    firstBookedDay,
    formatDay,
    pastCalendarWeeks,
  } from "../domain/slots";
  import { today } from "../domain/time";
  import { live } from "../lib/live.svelte";
  import { sync } from "../sync/store.svelte";
  import type { DaySlot } from "../sync/types";

  let { database }: { database: LocalDatabase } = $props();

  const projects = live(() => database.projects.toArray(), []);
  const slots = live(() => database.daySlots.toArray(), []);

  let until = $state(addDays(today(), -1));
  const byUid = $derived(new Map(projects.value.map((p) => [p.uid, p])));
  const weeks = $derived(pastCalendarWeeks(slots.value, ARCHIVE_WEEKS, until));
  const earliest = $derived(firstBookedDay(slots.value));
  const olderPage = $derived(addDays(until, -(ARCHIVE_WEEKS * 7)));
  const hasOlder = $derived(earliest !== null && olderPage >= earliest);

  async function toggleDone(booking: DaySlot) {
    await updateRow<DaySlot>(database, "day_slot", booking.uid, { is_done: !booking.is_done });
    await sync.refresh();
    void sync.run();
  }
</script>

<section class="page">
  <header class="head">
    <h1>Archive</h1>
    <span class="muted">up to {formatDay(until)}</span>
  </header>

  {#each weeks as week, index (index)}
    <div class="week">
      {#each week as sheet (sheet.date)}
        <article class="sheet">
          <h2>{formatDay(sheet.date)}</h2>
          {#each SLOTS as name (name)}
            {@const booking = sheet.slots[name]}
            {@const project = booking?.project_uid ? byUid.get(booking.project_uid) : undefined}
            <div class="cell" data-state={booking ? (booking.is_done ? "done" : "booked") : "free"}>
              <span class="cell-slot">{name}</span>
              <span class="cell-title">{project?.title ?? (booking ? "Unknown" : "—")}</span>
              {#if booking}
                <button type="button" title="Tick this session off" onclick={() => toggleDone(booking)}>✓</button>
              {/if}
            </div>
          {/each}
        </article>
      {/each}
    </div>
  {/each}

  <div class="pager">
    {#if hasOlder}
      <button type="button" class="btn" onclick={() => (until = olderPage)}>Older</button>
    {:else}
      <span class="muted">That is as far back as the bookings go.</span>
    {/if}
    {#if until < addDays(today(), -1)}
      <button type="button" class="btn ghost" onclick={() => (until = addDays(today(), -1))}>Newest</button>
    {/if}
  </div>
</section>

<style>
  .page { max-width: 68rem; margin: 0 auto; padding: 1.5rem 1rem 4rem; }
  .head { display: flex; align-items: baseline; justify-content: space-between; gap: 1rem; }
  h1 { font-size: 1.6rem; margin: 0; }
  .muted { opacity: 0.6; font-size: 0.85rem; }
  .week { display: grid; grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr)); gap: 0.6rem; margin-top: 0.9rem; }
  .sheet { border: 1px solid rgba(127, 127, 127, 0.22); border-radius: 0.7rem; padding: 0.5rem; opacity: 0.92; }
  .sheet h2 { font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.05em; opacity: 0.6; margin: 0 0 0.4rem; }
  .cell { display: flex; align-items: center; gap: 0.4rem; border: 1px dashed rgba(127, 127, 127, 0.35); border-radius: 0.45rem; padding: 0.3rem 0.4rem; margin-bottom: 0.3rem; }
  .cell[data-state="booked"] { border-style: solid; border-color: #d97706; }
  .cell[data-state="done"] { border-style: solid; border-color: #16a34a; }
  .cell-slot { font-weight: 700; opacity: 0.5; font-size: 0.75rem; }
  .cell-title { font-size: 0.8rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; }
  .cell button { background: none; border: 0; color: inherit; opacity: 0.55; cursor: pointer; }
  .cell button:hover { opacity: 1; }
  .pager { display: flex; gap: 0.75rem; align-items: center; margin-top: 1.5rem; }
  .btn { border: 1px solid rgba(127, 127, 127, 0.35); background: transparent; color: inherit; border-radius: 0.5rem; padding: 0.35rem 0.9rem; cursor: pointer; }
</style>

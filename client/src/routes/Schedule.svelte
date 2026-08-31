<script lang="ts">
  /**
   * A month of day sheets, bookable in place.
   *
   * Every rule comes from domain/slots.ts, so a refusal reads the same here as
   * it did on the server. Changes are applied locally first and the queue takes
   * them onward - which is why a booking made with no network still appears.
   */
  import { createRow, deleteRow, updateRow } from "../db/mutate";
  import type { LocalDatabase } from "../db/schema";
  import {
    SLOTS,
    calendarWeeks,
    formatDay,
    planAssign,
    planDayOff,
    planMove,
    slotCandidates,
    weeksToCover,
  } from "../domain/slots";
  import { today } from "../domain/time";
  import { live } from "../lib/live.svelte";
  import { BASE, link } from "../lib/router.svelte";
  import { sync } from "../sync/store.svelte";
  import type { DaySlot } from "../sync/types";

  let { database }: { database: LocalDatabase } = $props();

  const projects = live(() => database.projects.toArray(), []);
  const slots = live(() => database.daySlots.toArray(), []);

  const day = today();
  const weeks = $derived(calendarWeeks(slots.value, weeksToCover(slots.value, day), day));
  const byUid = $derived(new Map(projects.value.map((p) => [p.uid, p])));

  let picking = $state<{ date: string; slot: string } | null>(null);
  /** Tapping a booking then a target moves it - HTML5 drag does not fire on a phone. */
  let holding = $state<{ date: string; slot: string } | null>(null);
  let notice = $state("");

  const candidates = $derived(
    picking
      ? slotCandidates(projects.value, slots.value, picking.date, picking.slot, day)
      : []
  );

  function announce(message: string) {
    notice = message;
    setTimeout(() => (notice = message === notice ? "" : notice), 4000);
  }

  async function afterWrite(message: string) {
    announce(message);
    await sync.refresh();
    void sync.run();
  }

  async function book(projectUid: string) {
    if (!picking) return;
    const plan = planAssign(projects.value, slots.value, projectUid, picking.date, picking.slot, day);
    if (!plan.ok) return announce(plan.message);

    if (plan.create) await createRow<DaySlot>(database, "day_slot", plan.create);
    picking = null;
    await afterWrite(plan.message);
  }

  async function clear(booking: DaySlot) {
    await deleteRow(database, "day_slot", booking.uid);
    await afterWrite(`Slot ${booking.slot} cleared.`);
  }

  async function toggleDone(booking: DaySlot) {
    await updateRow<DaySlot>(database, "day_slot", booking.uid, { is_done: !booking.is_done });
    await afterWrite(booking.is_done ? "Marked as not done." : "Session ticked off.");
  }

  async function move(toDate: string, toSlot: string) {
    if (!holding) return;
    const from = holding;
    holding = null;

    const plan = planMove(projects.value, slots.value, from.date, from.slot, toDate, toSlot, day);
    if (!plan.ok) return announce(plan.message);

    for (const update of plan.updates ?? []) {
      await updateRow<DaySlot>(database, "day_slot", update.uid, update.changes);
    }
    await afterWrite(plan.message);
  }

  async function dayOff() {
    const date = window.prompt("Free which day? (YYYY-MM-DD)", day);
    if (!date) return;

    const plan = planDayOff(slots.value, date, 1, day);
    if (!plan.ok) return announce(plan.message);

    for (const update of plan.updates ?? []) {
      await updateRow<DaySlot>(database, "day_slot", update.uid, update.changes);
    }
    await afterWrite(plan.message);
  }

  function onCellClick(date: string, name: string, booking: DaySlot | null) {
    if (holding) return void move(date, name);
    if (booking) holding = { date, slot: name };
    else picking = { date, slot: name };
  }
</script>

<section class="page">
  <header class="head">
    <h1>Schedule</h1>
    <div class="actions">
      {#if holding}
        <span class="hint">Pick where it goes, or <button type="button" class="linkish" onclick={() => (holding = null)}>cancel</button></span>
      {/if}
      <button type="button" class="btn ghost" onclick={dayOff}>Day off</button>
    </div>
  </header>

  {#if notice}<p class="notice">{notice}</p>{/if}

  {#each weeks as week, index (index)}
    <div class="week">
      {#each week as sheet (sheet.date)}
        <article class="sheet" class:today={sheet.date === day}>
          <h2>{formatDay(sheet.date)}</h2>
          {#each SLOTS as name (name)}
            {@const booking = sheet.slots[name]}
            {@const project = booking?.project_uid ? byUid.get(booking.project_uid) : undefined}
            <div
              class="cell"
              data-state={booking ? (booking.is_done ? "done" : "booked") : "free"}
              class:holding={holding?.date === sheet.date && holding?.slot === name}
            >
              <button type="button" class="cell-main" onclick={() => onCellClick(sheet.date, name, booking)}>
                <span class="cell-slot">{name}</span>
                <span class="cell-title">{project?.title ?? (booking ? "Unknown" : "—")}</span>
              </button>
              {#if booking}
                <span class="cell-tools">
                  <button type="button" title="Tick this session off" onclick={() => toggleDone(booking)}>✓</button>
                  <button type="button" title="Free this slot" onclick={() => clear(booking)}>×</button>
                </span>
              {/if}
            </div>
          {/each}
        </article>
      {/each}
    </div>
  {/each}
</section>

{#if picking}
  <div class="overlay" role="dialog" aria-label="Choose a project">
    <div class="panel">
      <header>
        <strong>{formatDay(picking.date)} · slot {picking.slot}</strong>
        <button type="button" class="linkish" onclick={() => (picking = null)}>Close</button>
      </header>
      <ul class="candidates">
        {#each candidates as candidate (candidate.uid)}
          <li>
            <button type="button" disabled={!candidate.canTake} onclick={() => book(candidate.uid)}>
              <span class="candidate-title">
                {candidate.isStarred ? "★ " : ""}{candidate.title}
              </span>
              {#if candidate.planHeading}<span class="muted">{candidate.planHeading}</span>{/if}
              {#if candidate.reason}<span class="reason">{candidate.reason}</span>{/if}
            </button>
          </li>
        {/each}
      </ul>
      <a href={`${BASE}`} use:link class="muted small">Back to today</a>
    </div>
  </div>
{/if}

<style>
  .page { max-width: 68rem; margin: 0 auto; padding: 1.5rem 1rem 4rem; }
  .head { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
  h1 { font-size: 1.6rem; margin: 0; }
  .actions { display: flex; align-items: center; gap: 0.75rem; }
  .hint { font-size: 0.82rem; opacity: 0.75; }
  .notice { background: rgba(217, 119, 6, 0.12); border-radius: 0.5rem; padding: 0.5rem 0.75rem; font-size: 0.88rem; }
  .btn { border: 1px solid rgba(127, 127, 127, 0.35); background: transparent; color: inherit; border-radius: 0.5rem; padding: 0.3rem 0.8rem; cursor: pointer; }
  .linkish { background: none; border: 0; color: inherit; text-decoration: underline; cursor: pointer; font: inherit; }

  .week { display: grid; grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr)); gap: 0.6rem; margin-top: 0.9rem; }
  .sheet { border: 1px solid rgba(127, 127, 127, 0.22); border-radius: 0.7rem; padding: 0.5rem; }
  .sheet.today { border-color: var(--bs-primary, #4f46e5); }
  .sheet h2 { font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.05em; opacity: 0.6; margin: 0 0 0.4rem; }

  .cell { display: flex; align-items: center; gap: 0.25rem; border: 1px dashed rgba(127, 127, 127, 0.4); border-radius: 0.45rem; margin-bottom: 0.3rem; }
  .cell[data-state="booked"] { border-style: solid; border-color: #d97706; }
  .cell[data-state="done"] { border-style: solid; border-color: #16a34a; }
  .cell.holding { outline: 2px solid var(--bs-primary, #4f46e5); }
  .cell-main { flex: 1; display: flex; gap: 0.4rem; align-items: baseline; background: none; border: 0; color: inherit; padding: 0.35rem 0.4rem; cursor: pointer; text-align: left; font: inherit; min-width: 0; }
  .cell-slot { font-weight: 700; opacity: 0.5; font-size: 0.75rem; }
  .cell-title { font-size: 0.8rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .cell-tools { display: flex; }
  .cell-tools button { background: none; border: 0; color: inherit; opacity: 0.55; cursor: pointer; padding: 0.2rem 0.3rem; }
  .cell-tools button:hover { opacity: 1; }

  .overlay { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.35); display: grid; place-items: center; padding: 1rem; z-index: 50; }
  .panel { background: var(--app-surface, Canvas); border-radius: 0.9rem; padding: 1rem; width: min(30rem, 100%); max-height: 80vh; overflow: auto; }
  .panel header { display: flex; justify-content: space-between; margin-bottom: 0.6rem; }
  .candidates { list-style: none; margin: 0 0 0.75rem; padding: 0; }
  .candidates button { width: 100%; display: flex; flex-direction: column; gap: 0.1rem; text-align: left; background: none; border: 0; border-bottom: 1px solid rgba(127, 127, 127, 0.15); padding: 0.5rem 0.25rem; color: inherit; cursor: pointer; font: inherit; }
  .candidates button:disabled { opacity: 0.45; cursor: not-allowed; }
  .candidate-title { font-weight: 600; }
  .muted { opacity: 0.6; font-size: 0.8rem; }
  .small { font-size: 0.8rem; }
  .reason { font-size: 0.78rem; color: #b45309; }
</style>

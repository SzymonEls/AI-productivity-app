<script lang="ts">
  /**
   * A month of day sheets, bookable in place.
   *
   * Every rule comes from domain/slots.ts, so a refusal reads the same here as
   * it did on the server. Changes are applied locally first and the queue takes
   * them onward - which is why a booking made with no network still appears.
   */
  import { deleteRow, updateRow } from "../db/mutate";
  import type { LocalDatabase } from "../db/schema";
  import {
    type SheetSlot,
    calendarWeeks,
    dateRangeLabel,
    planDayOff,
    planMove,
    scheduleSheet,
    weekLabel,
    weeksToCover,
  } from "../domain/slots";
  import { today } from "../domain/time";
  import { live } from "../lib/live.svelte";
  import { BASE, link } from "../lib/router.svelte";
  import { sync } from "../sync/store.svelte";
  import type { DaySlot } from "../sync/types";
  import DaySheet from "../ui/DaySheet.svelte";
  import Planner from "../ui/Planner.svelte";
  import Icon from "../ui/Icon.svelte";

  let { database }: { database: LocalDatabase } = $props();

  const projects = live(() => database.projects.toArray(), []);
  const slots = live(() => database.daySlots.toArray(), []);

  const day = today();
  const byUid = $derived(new Map(projects.value.map((p) => [p.uid, p])));
  const weekCount = $derived(weeksToCover(slots.value, day));
  const weeks = $derived(
    calendarWeeks(slots.value, weekCount, day).map((week, index) => ({
      label: weekLabel(index),
      range: dateRangeLabel(week[0].date, week[week.length - 1].date),
      sheets: week.map((calendarDay) => scheduleSheet(calendarDay, byUid, day)),
    }))
  );

  let picking = $state<{ date: string; slot: string } | null>(null);
  let holding = $state<{ date: string; slot: string } | null>(null);
  // A drag crosses sheets, so the board holds what is being dragged.
  let dragging = $state<{ date: string; slot: string } | null>(null);
  let dayOffOpen = $state(false);
  let dayOffDate = $state(day);
  let status = $state("");


  function announce(message: string) {
    status = message;
    setTimeout(() => (status = status === message ? "" : status), 5000);
  }

  async function after(message: string) {
    announce(message);
    await sync.refresh();
    void sync.run();
  }


  async function clear(entry: SheetSlot) {
    if (!entry.booking) return;
    await deleteRow(database, "day_slot", entry.booking.uid);
    await after(`Slot ${entry.slot} cleared.`);
  }

  /** A drag that landed: the same move a pair of taps makes. */
  async function move(from: { date: string; slot: string }, to: { date: string; slot: string }) {
    holding = null;
    const plan = planMove(projects.value, slots.value, from.date, from.slot, to.date, to.slot, day);
    if (!plan.ok) return announce(plan.message);
    for (const update of plan.updates ?? []) {
      await updateRow<DaySlot>(database, "day_slot", update.uid, update.changes);
    }
    await after(plan.message);
  }

  async function pick(date: string, slot: string, entry: SheetSlot) {
    if (!holding) {
      if (entry.project) holding = { date, slot };
      return;
    }

    const from = holding;
    holding = null;
    if (from.date === date && from.slot === slot) return;
    await move(from, { date, slot });
  }

  async function takeDayOff() {
    const plan = planDayOff(slots.value, dayOffDate, 1, day);
    dayOffOpen = false;
    if (!plan.ok) return announce(plan.message);
    for (const update of plan.updates ?? []) {
      await updateRow<DaySlot>(database, "day_slot", update.uid, update.changes);
    }
    await after(plan.message);
  }
</script>

<div class="dashboard-page schedule-page">
  <section class="dashboard-section dashboard-header-section">
    <div class="d-flex justify-content-between align-items-center gap-3 flex-wrap">
      <div class="d-flex align-items-center gap-2">
        <h1 class="h5 mb-0">Schedule</h1>
        <span class="text-muted small">The next {weekCount} weeks, one sheet per day.</span>
      </div>
      <div class="d-flex align-items-center gap-2">
        <span class="schedule-status" role="status">{status}</span>
        <button type="button" class="btn btn-outline-secondary btn-sm" onclick={() => (dayOffOpen = true)}>
          <Icon name="moon" />Day off
        </button>
        <a href={`${BASE}/archive`} use:link class="btn btn-outline-secondary btn-sm">
          <Icon name="archive" />Archive
        </a>
        <a href={`${BASE}/`} use:link class="btn btn-outline-secondary btn-sm">
          <Icon name="home" />Today
        </a>
      </div>
    </div>
    <p class="schedule-hint">
      Drag a project onto another block to move it, or tap it and then tap where
      it should go. Dropping it on a taken block swaps the two. "Day off" asks
      for a date and frees it: that day and everything planned after it move one
      day later.
    </p>
  </section>

  {#each weeks as week (week.label)}
    <section class="schedule-week">
      <header class="schedule-week-header">
        <h2 class="schedule-week-title">{week.label}</h2>
        <span class="schedule-week-range">{week.range}</span>
      </header>
      <div class="schedule-grid">
        {#each week.sheets as sheet (sheet.date)}
          <DaySheet
            {sheet}
            {holding}
            {dragging}
            onfill={(date, slot) => (picking = { date, slot })}
            onclear={clear}
            onpick={pick}
            ondragbooking={(from) => (dragging = from)}
            ondropmove={move}
          />
        {/each}
      </div>
    </section>
  {/each}
</div>

{#if picking}
  <Planner {database} forSlot={picking} onclose={() => (picking = null)} />
{/if}

{#if dayOffOpen}
  <div class="planner-backdrop">
    <div class="planner-dialog planner-dialog-narrow" role="dialog" aria-label="Take a day off">
      <header class="planner-header">
        <h2 class="planner-title">Day off</h2>
        <button type="button" class="icon-button" title="Close" onclick={() => (dayOffOpen = false)}>
          <Icon name="x" />
        </button>
      </header>
      <p class="text-muted small">
        That day is freed, and everything planned for it and after it moves one
        day later. A session already ticked off stays where it happened.
      </p>
      <label class="d-block mb-3">
        <span class="text-muted small">Which day?</span>
        <input type="date" class="form-control" bind:value={dayOffDate} min={day} />
      </label>
      <button type="button" class="btn btn-primary btn-sm" onclick={takeDayOff}>Free that day</button>
    </div>
  </div>
{/if}

<script lang="ts">
  /**
   * Days already gone.
   *
   * A record, not a board: past blocks cannot be booked, moved or freed. The ✓
   * stays, because a session finished on Tuesday can be ticked off on Thursday
   * and still counts towards the health ring.
   */
  import { updateRow } from "../db/mutate";
  import type { LocalDatabase } from "../db/schema";
  import {
    ARCHIVE_WEEKS,
    type SheetSlot,
    addDays,
    archivePaging,
    dateRangeLabel,
    pastCalendarWeeks,
    pastWeekLabel,
    scheduleSheet,
  } from "../domain/slots";
  import { today } from "../domain/time";
  import { live } from "../lib/live.svelte";
  import { BASE, link } from "../lib/router.svelte";
  import { sync } from "../sync/store.svelte";
  import type { DaySlot } from "../sync/types";
  import DaySheet from "../ui/DaySheet.svelte";
  import Icon from "../ui/Icon.svelte";

  let { database }: { database: LocalDatabase } = $props();

  const projects = live(() => database.projects.toArray(), []);
  const slots = live(() => database.daySlots.toArray(), []);

  const day = today();

  let until = $state(addDays(today(), -1));
  let status = $state("");

  const byUid = $derived(new Map(projects.value.map((p) => [p.uid, p])));
  const weeks = $derived(
    pastCalendarWeeks(slots.value, ARCHIVE_WEEKS, until).map((week) => ({
      label: pastWeekLabel(week[0].date, day),
      range: dateRangeLabel(week[0].date, week[week.length - 1].date),
      sheets: week.map((calendarDay) => scheduleSheet(calendarDay, byUid, day)),
    }))
  );
  const bookedCount = $derived(
    weeks.reduce((total, week) => total + week.sheets.reduce((n, s) => n + s.bookedCount, 0), 0)
  );

  const paging = $derived(archivePaging(slots.value, until, day));
  const rangeLabel = $derived(dateRangeLabel(paging.firstDay, paging.lastDay));

  async function toggleDone(entry: SheetSlot) {
    if (!entry.booking) return;
    await updateRow<DaySlot>(database, "day_slot", entry.booking.uid, {
      is_done: !entry.booking.is_done,
    });
    status = entry.booking.is_done ? "Session reopened." : "Session ticked off.";
    setTimeout(() => (status = ""), 4000);
    await sync.refresh();
    void sync.run();
  }
</script>

<div class="dashboard-page schedule-archive-page">
  <section class="dashboard-section dashboard-header-section">
    <div class="d-flex justify-content-between align-items-center gap-3 flex-wrap">
      <div class="d-flex align-items-center gap-2">
        <h1 class="h5 mb-0">Archive</h1>
        <span class="text-muted small">Days that have already been · {rangeLabel}</span>
      </div>
      <div class="d-flex align-items-center gap-2">
        <span class="schedule-status" role="status">{status}</span>
        <!-- Each step is worked out from this page's own edges, so the pages
             meet exactly whatever weekday the newest one ends on. -->
        {#if paging.earlierUntil}
          <button type="button" class="btn btn-outline-secondary btn-sm" onclick={() => (until = paging.earlierUntil!)}>
            Earlier
          </button>
        {/if}
        {#if paging.laterUntil}
          <button type="button" class="btn btn-outline-secondary btn-sm" onclick={() => (until = paging.laterUntil!)}>
            Later
          </button>
        {/if}
        <a href={`${BASE}/schedule`} use:link class="btn btn-outline-secondary btn-sm">
          <Icon name="calendar" />Schedule
        </a>
      </div>
    </div>
    <p class="schedule-hint">
      A record, not a board: past blocks cannot be booked, moved or freed. The ✓
      marks a session that was ticked off — click it to tick one off now, or to
      reopen it, on any day that has been.
    </p>
  </section>

  {#if !bookedCount}
    <section class="dashboard-section">
      <p class="text-muted small mb-0">Nothing was booked in these three weeks.</p>
    </section>
  {/if}

  {#each weeks as week (week.range)}
    <section class="schedule-week">
      <header class="schedule-week-header">
        <h2 class="schedule-week-title">{week.label}</h2>
        <span class="schedule-week-range">{week.range}</span>
      </header>
      <div class="schedule-grid">
        {#each week.sheets as sheet (sheet.date)}
          <DaySheet {sheet} readonly ontoggledone={toggleDone} />
        {/each}
      </div>
    </section>
  {/each}
</div>

<script lang="ts">
  /**
   * One day's calendar sheet, shared by the schedule board and the archive.
   *
   * `readonly` drops everything that changes a booking. Nothing in the past can
   * be booked, moved or freed - but it keeps the ✓, which ticks a session off
   * after the fact: that changes what a day says happened, not what is planned
   * for it, so it is the one thing the past still answers.
   */
  import type { Sheet, SheetSlot } from "../domain/slots";
  import { BASE, link } from "../lib/router.svelte";
  import Icon from "./Icon.svelte";

  let {
    sheet,
    readonly = false,
    holding = null,
    onfill,
    onclear,
    ontoggledone,
    onpick,
  }: {
    sheet: Sheet;
    readonly?: boolean;
    holding?: { date: string; slot: string } | null;
    onfill?: (date: string, slot: string) => void;
    onclear?: (entry: SheetSlot) => void;
    ontoggledone?: (entry: SheetSlot) => void;
    onpick?: (date: string, slot: string, entry: SheetSlot) => void;
  } = $props();

  const weekday = (iso: string) =>
    new Intl.DateTimeFormat("en-GB", { weekday: "short", timeZone: "UTC" }).format(
      new Date(`${iso}T00:00:00Z`)
    );
  const dayNumber = (iso: string) => iso.slice(8, 10);
  const monthName = (iso: string) =>
    new Intl.DateTimeFormat("en-GB", { month: "short", timeZone: "UTC" }).format(
      new Date(`${iso}T00:00:00Z`)
    );
</script>

<article
  class="day-sheet"
  class:day-sheet-today={sheet.isToday}
  class:day-sheet-weekend={sheet.isWeekend}
  class:day-sheet-quiet={!sheet.bookedCount}
>
  <header class="day-sheet-header">
    <span class="day-sheet-weekday">{weekday(sheet.date)}</span>
    <span class="day-sheet-number">{dayNumber(sheet.date)}</span>
    <span class="day-sheet-month">{monthName(sheet.date)}</span>
    {#if sheet.isToday}<span class="day-sheet-tag">Today</span>{/if}
  </header>

  <ul class="day-sheet-slots">
    {#each sheet.slots as entry (entry.slot)}
      <li
        class="day-slot"
        class:day-slot-optional={entry.isOptional}
        class:is-booked={entry.project}
        class:is-free={!entry.project}
        class:is-done={entry.isDone}
        class:is-holding={holding?.date === sheet.date && holding?.slot === entry.slot}
      >
        <span class="day-slot-letter" aria-hidden="true">{entry.slot}</span>
        <div class="day-slot-content">
          {#if entry.project}
            <a class="day-slot-title" href={`${BASE}/projects/${entry.project.uid}`} use:link>
              {entry.project.title}
            </a>
            {#if entry.isDone && !readonly}
              <span class="day-slot-done" title="Session done" aria-label="Session done">✓</span>
            {/if}
            {#if entry.planHeading}<span class="day-slot-step">{entry.planHeading}</span>{/if}
          {:else}
            <span class="day-slot-free">Free</span>
          {/if}
        </div>

        {#if readonly && entry.project}
          <!-- The one thing a past block can still be told: that it happened. -->
          <button
            type="button"
            class="icon-button day-slot-done-toggle"
            aria-pressed={entry.isDone}
            title={entry.isDone ? "Session done — click to reopen" : "Mark this session done"}
            onclick={() => ontoggledone?.(entry)}
          ><Icon name="check" /></button>
        {/if}

        {#if !readonly}
          {#if entry.project}
            <!-- Tap to pick the booking up, then tap where it goes. A grip
                 rather than the whole block, so the title stays a link -
                 and unlike HTML5 drag, this works on a phone. -->
            <button
              type="button"
              class="icon-button day-slot-move"
              title={`Move block ${entry.slot}`}
              onclick={() => onpick?.(sheet.date, entry.slot, entry)}
            >⇄</button>
            <button
              type="button"
              class="icon-button day-slot-clear"
              title={`Free block ${entry.slot}`}
              onclick={() => onclear?.(entry)}
            ><Icon name="x" /></button>
          {/if}
          <!-- Covers the whole block: an empty one is one click from a project,
               and any block is a target while something is being moved. -->
          {#if !entry.project || holding}
            <button
              type="button"
              class="day-slot-fill"
              onclick={() =>
                holding
                  ? onpick?.(sheet.date, entry.slot, entry)
                  : onfill?.(sheet.date, entry.slot)}
            >
              <span class="visually-hidden">
                {holding ? `Move here, block ${entry.slot}` : `Choose a project for block ${entry.slot}`}
              </span>
            </button>
          {/if}
        {/if}
      </li>
    {/each}
  </ul>
</article>

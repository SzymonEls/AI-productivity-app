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
    dragging = null,
    ondragbooking,
    ondropmove,
  }: {
    sheet: Sheet;
    readonly?: boolean;
    holding?: { date: string; slot: string } | null;
    onfill?: (date: string, slot: string) => void;
    onclear?: (entry: SheetSlot) => void;
    ontoggledone?: (entry: SheetSlot) => void;
    onpick?: (date: string, slot: string, entry: SheetSlot) => void;
    /** The booking being dragged, if any - the board owns it, since a drag
        starts in one sheet and ends in another. */
    dragging?: { date: string; slot: string } | null;
    ondragbooking?: (from: { date: string; slot: string } | null) => void;
    ondropmove?: (from: { date: string; slot: string }, to: { date: string; slot: string }) => void;
  } = $props();

  // Which block the pointer is over, so it can light up.
  let over = $state<string | null>(null);

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
        class:is-picked={holding?.date === sheet.date && holding?.slot === entry.slot}
        class:is-drag-over={over === entry.slot}
        ondragover={(event) => {
          if (readonly || !dragging) return;
          // Without preventDefault the browser refuses the drop.
          event.preventDefault();
          event.dataTransfer!.dropEffect = "move";
          over = entry.slot;
        }}
        ondragleave={() => (over = over === entry.slot ? null : over)}
        ondrop={(event) => {
          if (readonly || !dragging) return;
          event.preventDefault();
          over = null;
          const from = dragging;
          ondragbooking?.(null);
          if (from.date !== sheet.date || from.slot !== entry.slot) {
            ondropmove?.(from, { date: sheet.date, slot: entry.slot });
          }
        }}
      >
        <span class="day-slot-letter" aria-hidden="true">{entry.slot}</span>
        <!-- Dragging is a pointer convenience on top of tapping: the overlay
             button below is the keyboard path, so this carries no role. -->
        <div
          class="day-slot-content"
          class:is-dragging={dragging?.date === sheet.date && dragging?.slot === entry.slot}
          draggable={!readonly && Boolean(entry.project)}
          role="none"
          ondragstart={(event) => {
            if (readonly || !entry.project) {
              event.preventDefault();
              return;
            }
            ondragbooking?.({ date: sheet.date, slot: entry.slot });
            event.dataTransfer!.effectAllowed = "move";
            // Firefox only starts a drag once the payload is set.
            event.dataTransfer!.setData("text/plain", entry.project.uid);
          }}
          ondragend={() => {
            ondragbooking?.(null);
            over = null;
          }}
        >
          {#if entry.project && readonly}
            <a class="day-slot-title" href={`${BASE}/projects/${entry.project.uid}`} use:link>
              {entry.project.title}
            </a>
          {:else if entry.project}
            <span class="day-slot-title">{entry.project.title}</span>
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
            <button
              type="button"
              class="icon-button day-slot-clear"
              title={`Free block ${entry.slot}`}
              onclick={(event) => {
                // The cell below would otherwise read this as "pick it up".
                event.stopPropagation();
                onclear?.(entry);
              }}
            ><Icon name="x" /></button>
          {/if}
          <!-- Covers the whole block, booked or not. On the board a click means
               "move this", not "open it", so the title is not a way out either -
               tap a booking to pick it up, then tap where it goes. -->
          <button
            type="button"
            class="day-slot-fill"
            onclick={() =>
              holding || entry.project
                ? onpick?.(sheet.date, entry.slot, entry)
                : onfill?.(sheet.date, entry.slot)}
          >
            <span class="visually-hidden">
              {#if holding}
                Move here, block {entry.slot}
              {:else if entry.project}
                Move block {entry.slot}
              {:else}
                Choose a project for block {entry.slot}
              {/if}
            </span>
          </button>
        {/if}
      </li>
    {/each}
  </ul>
</article>

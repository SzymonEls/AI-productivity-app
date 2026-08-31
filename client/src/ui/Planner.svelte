<script lang="ts">
  /**
   * The session planner, in its two shapes.
   *
   * From a project: a fortnight of days, each with its three blocks, and a
   * "Take" on the ones the two-block rule allows. From an empty block: the
   * project list for that one spot, blocked ones shown with the reason rather
   * than missing.
   */
  import { createRow } from "../db/mutate";
  import type { LocalDatabase } from "../db/schema";
  import {
    bookingNote,
    formatDay,
    planAssign,
    scheduleWindow,
    slotCandidates,
  } from "../domain/slots";
  import { today } from "../domain/time";
  import { live } from "../lib/live.svelte";
  import { sync } from "../sync/store.svelte";
  import type { DaySlot } from "../sync/types";

  let {
    database,
    forProject = null,
    forSlot = null,
    onclose,
  }: {
    database: LocalDatabase;
    /** Plan a project: which day and block should it take? */
    forProject?: { uid: string; title: string } | null;
    /** Fill a block: which project should go here? */
    forSlot?: { date: string; slot: string } | null;
    onclose: () => void;
  } = $props();

  const projects = live(() => database.projects.toArray(), []);
  const slots = live(() => database.daySlots.toArray(), []);

  const day = today();
  let status = $state("");

  const window_ = $derived(
    forProject ? scheduleWindow(projects.value, slots.value, forProject.uid, 14, day) : []
  );
  const note = $derived(forProject ? bookingNote(slots.value, forProject.uid, day) : "");
  const candidates = $derived(
    forSlot ? slotCandidates(projects.value, slots.value, forSlot.date, forSlot.slot, day) : []
  );

  async function take(projectUid: string, date: string, slot: string) {
    const plan = planAssign(projects.value, slots.value, projectUid, date, slot, day);
    if (!plan.ok) {
      status = plan.message;
      return;
    }
    if (plan.create) await createRow<DaySlot>(database, "day_slot", plan.create);
    status = plan.message;
    await sync.refresh();
    void sync.run();
    onclose();
  }
</script>

<div class="planner-backdrop">
  <div class="planner-dialog" role="dialog" aria-modal="true" aria-label="Session planner">
    <header class="planner-header">
      <h2 class="h6 mb-0">
        {#if forProject}
          Plan next session · {forProject.title}
        {:else if forSlot}
          {formatDay(forSlot.date)} · block {forSlot.slot}
        {/if}
      </h2>
      <button type="button" class="icon-button" aria-label="Close" onclick={onclose}>×</button>
    </header>

    {#if status}<p class="planner-status" role="status">{status}</p>{/if}
    {#if note}<p class="planner-note">{note}</p>{/if}

    {#if forProject}
      <div class="planner-grid">
        {#each window_ as entry (entry.date)}
          <div class="planner-day" class:planner-day-today={entry.isToday}>
            <div class="planner-day-label">
              {entry.label}{#if entry.isToday} · today{/if}
            </div>
            <div class="planner-day-slots">
              {#each entry.slots as block (block.slot)}
                <div
                  class="planner-slot"
                  class:planner-slot-free={!block.projectUid}
                  class:planner-slot-optional={block.isOptional}
                  class:planner-slot-mine={block.isThisProject}
                  class:planner-slot-done={block.isDone}
                >
                  <span class="planner-slot-letter">{block.slot}</span>
                  {#if block.canTake}
                    <button
                      type="button"
                      class="btn btn-outline-secondary btn-sm planner-take"
                      onclick={() => take(forProject.uid, entry.date, block.slot)}
                    >Take</button>
                  {:else if block.projectUid}
                    <span class="planner-slot-taken">{block.projectTitle}</span>
                  {/if}
                </div>
              {/each}
            </div>
          </div>
        {/each}
      </div>
    {:else if forSlot}
      <ul class="planner-projects">
        {#each candidates as candidate (candidate.uid)}
          <li>
            <button
              type="button"
              class="planner-project"
              class:is-blocked={!candidate.canTake}
              disabled={!candidate.canTake}
              onclick={() => take(candidate.uid, forSlot.date, forSlot.slot)}
            >
              <span class="planner-project-title">
                {#if candidate.isStarred}<span class="switcher-badge" aria-hidden="true">★</span>{/if}
                {candidate.title}
              </span>
              {#if candidate.planHeading}
                <span class="planner-project-step">{candidate.planHeading}</span>
              {/if}
              {#if candidate.reason}
                <span class="planner-project-reason">{candidate.reason}</span>
              {/if}
            </button>
          </li>
        {/each}
      </ul>
    {/if}
  </div>
</div>

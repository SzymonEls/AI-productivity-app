<script lang="ts">
  /**
   * The session planner, in its two shapes.
   *
   * From a project: a fortnight of days, each with its three blocks, and a
   * "Take" on the ones the two-block rule allows. From an empty block: the
   * project list for that one spot, blocked ones shown with the reason rather
   * than missing.
   */
  import { createRow, deleteRow } from "../db/mutate";
  import type { LocalDatabase } from "../db/schema";
  import {
    bookingNote,
    planAssign,
    scheduleWindow,
    slotCandidates,
  } from "../domain/slots";
  import { today } from "../domain/time";
  import { dismissable } from "../lib/dismiss";
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
  const entries = live(() => database.timeEntries.toArray(), []);

  const lastSessionOf = $derived.by(() => {
    const latest = new Map<string, string>();
    for (const entry of entries.value) {
      if (!entry.project_uid) continue;
      const seen = latest.get(entry.project_uid);
      if (!seen || entry.started_at > seen) latest.set(entry.project_uid, entry.started_at);
    }
    return latest;
  });

  const day = today();
  let status = $state("");
  /** "success" or "danger", the two tones the status line has always had. */
  let tone = $state("");

  const window_ = $derived(
    forProject ? scheduleWindow(projects.value, slots.value, forProject.uid, 14, day) : []
  );
  const note = $derived(forProject ? bookingNote(slots.value, forProject.uid, day) : "");
  const candidates = $derived(
    forSlot
      ? slotCandidates(projects.value, slots.value, forSlot.date, forSlot.slot, day, lastSessionOf)
      : []
  );

  function say(message: string, next = "") {
    status = message;
    tone = next;
  }

  async function take(projectUid: string, date: string, slot: string) {
    const plan = planAssign(projects.value, slots.value, projectUid, date, slot, day);
    if (!plan.ok) return say(plan.message, "danger");

    if (plan.create) await createRow<DaySlot>(database, "day_slot", plan.create);
    say(plan.message, "success");
    await sync.refresh();
    void sync.run();
    // Planning a project stays open on the redrawn grid, the way the original
    // did; picking a project for one block has answered its own question.
    if (forSlot) onclose();
  }

  /**
   * Free a block from inside the dialog.
   *
   * Any booked block, not only this project's: the grid shows a fortnight, and
   * "that Tuesday belongs to something else" is exactly what you want to undo
   * while planning.
   */
  async function release(bookingUid: string, slot: string) {
    await deleteRow(database, "day_slot", bookingUid);
    say(`Slot ${slot} cleared.`, "success");
    await sync.refresh();
    void sync.run();
  }
</script>

<div class="planner-backdrop" use:dismissable={onclose}>
  <div class="planner-dialog" role="dialog" aria-modal="true" aria-label="Session planner">
    <header class="planner-header">
      <h2 class="h6 mb-0">
        {#if forProject}
          Plan next session · {forProject.title}
        {:else if forSlot}
          Choose a project for slot {forSlot.slot}
        {/if}
      </h2>
      <button type="button" class="icon-button" aria-label="Close" onclick={onclose}>×</button>
    </header>

    {#if status}
      <p class={`planner-status${tone ? ` planner-status-${tone}` : ""}`} role="status">{status}</p>
    {/if}
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
                <!-- The cell carries the state, as it did on the original: amber
                     for a booked block, grey for the spare C, green once the
                     session is done, dashed while it is still free. -->
                <div
                  class="planner-slot"
                  class:planner-slot-optional={block.isOptional}
                  class:planner-slot-taken={block.projectUid}
                  class:planner-slot-mine={block.isThisProject}
                  class:planner-slot-done={block.isDone}
                  class:planner-slot-free={!block.projectUid && block.canTake}
                  class:planner-slot-blocked={!block.projectUid && !block.canTake}
                >
                  <span class="planner-slot-letter">{block.slot}</span>
                  {#if block.projectUid}
                    <span class="planner-slot-name">{block.projectTitle}</span>
                    <button
                      type="button"
                      class="planner-slot-remove"
                      title={`Free block ${block.slot}`}
                      aria-label={`Remove ${block.projectTitle} from block ${block.slot} on ${entry.label}`}
                      onclick={() => release(block.bookingUid!, block.slot)}
                    >×</button>
                  {:else if block.canTake}
                    <button
                      type="button"
                      class="btn btn-outline-secondary btn-sm planner-take"
                      onclick={() => take(forProject.uid, entry.date, block.slot)}
                    >Take</button>
                  {:else}
                    <span class="planner-slot-name">—</span>
                  {/if}
                </div>
              {/each}
            </div>
          </div>
        {/each}
      </div>
    {:else if forSlot}
      <div class="planner-grid">
        {#if candidates.length === 0}
          <p class="planner-status">You have no active projects yet.</p>
        {:else}
          <div class="picker-list">
            {#each candidates as candidate (candidate.uid)}
              {#if candidate.canTake}
                <button
                  type="button"
                  class="picker-row"
                  onclick={() => take(candidate.uid, forSlot.date, forSlot.slot)}
                >
                  <span class="picker-row-text">
                    <span class="picker-row-title">
                      {candidate.title}{#if candidate.isStarred}<span class="switcher-badge" aria-hidden="true">★</span>{/if}
                    </span>
                    <span class="picker-row-note">
                      {candidate.planHeading || candidate.lastSession}
                    </span>
                  </span>
                </button>
              {:else}
                <!-- Blocked ones are shown with the reason rather than missing:
                     "where did that project go" is worse than a greyed-out row
                     that explains itself. -->
                <div class="picker-row picker-row-blocked">
                  <span class="picker-row-text">
                    <span class="picker-row-title">
                      {candidate.title}{#if candidate.isStarred}<span class="switcher-badge" aria-hidden="true">★</span>{/if}
                    </span>
                    <span class="picker-row-note">{candidate.reason}</span>
                  </span>
                </div>
              {/if}
            {/each}
          </div>
        {/if}
      </div>
    {/if}
  </div>
</div>

<script lang="ts">
  /**
   * The project's timer.
   *
   * On the server this polled for its state; the entries are on this device
   * now, so the clock is worked out locally and the change goes out through the
   * queue like any other.
   */
  import { createRow, updateRow } from "../db/mutate";
  import type { LocalDatabase } from "../db/schema";
  import {
    activeEntry,
    dayBounds,
    elapsedSeconds,
    entriesForRange,
    formatDuration,
    overlapSeconds,
    today,
  } from "../domain/time";
  import { live } from "../lib/live.svelte";
  import { sync } from "../sync/store.svelte";
  import type { TimeEntry } from "../sync/types";

  let {
    database,
    projectUid,
    projectTitle,
    onclose,
  }: {
    database: LocalDatabase;
    projectUid: string;
    projectTitle: string;
    onclose: () => void;
  } = $props();

  const entries = live(() => database.timeEntries.toArray(), []);

  const day = today();
  let now = $state(new Date());
  $effect(() => {
    const timer = setInterval(() => (now = new Date()), 1000);
    return () => clearInterval(timer);
  });

  const bounds = $derived(dayBounds(day));
  const todays = $derived(
    entriesForRange(entries.value, bounds[0], bounds[1], projectUid)
  );
  const running = $derived(activeEntry(entries.value));
  const mineRunning = $derived(running?.project_uid === projectUid ? running : null);
  const total = $derived(
    todays.reduce((sum, entry) => sum + overlapSeconds(entry, bounds[0], bounds[1], now), 0)
  );

  let description = $state("");
  let saved = $state("");
  $effect(() => {
    description = mineRunning?.description ?? "";
  });

  async function after() {
    await sync.refresh();
    void sync.run();
  }

  async function start() {
    // One timer at a time, exactly as the server refused a second one.
    if (running) await stop();
    await createRow<TimeEntry>(database, "time_entry", {
      started_at: new Date().toISOString(),
      ended_at: null,
      description: null,
      // Written now, not when the project is deleted: it is what keeps past
      // weeks readable once the project is gone.
      project_title_snapshot: projectTitle,
      project_uid: projectUid,
    });
    await after();
  }

  async function stop() {
    if (!running) return;
    await updateRow<TimeEntry>(database, "time_entry", running.uid, {
      ended_at: new Date().toISOString(),
    });
    await after();
  }

  async function saveDescription() {
    const target = mineRunning ?? todays[0];
    if (!target) {
      saved = "No session to describe yet.";
      return;
    }
    await updateRow<TimeEntry>(database, "time_entry", target.uid, {
      description: description.trim() || null,
    });
    saved = "Saved.";
    setTimeout(() => (saved = ""), 3000);
    await after();
  }

  function clock(iso: string): string {
    return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }
</script>

<div class="modal-backdrop-shim">
  <div class="modal-dialog modal-dialog-centered">
    <div class="modal-content project-timer-modal">
      <div class="modal-header project-timer-modal-header">
        <div class="min-w-0">
          <h2 class="modal-title h5">Today's work time</h2>
          <span class="small text-muted">
            {mineRunning ? "Timer is running" : "Timer is stopped"}
          </span>
        </div>
        <strong class="project-timer-clock ms-auto">{formatDuration(total)}</strong>
        <button type="button" class="btn-close" aria-label="Close" onclick={onclose}></button>
      </div>

      <div class="modal-body">
        <div class="project-timer-actions mb-3">
          <button type="button" class="btn btn-success" disabled={Boolean(mineRunning)} onclick={start}>
            {mineRunning ? "Session in progress" : "Start new session"}
          </button>
          <button type="button" class="btn btn-outline-secondary" disabled={!mineRunning} onclick={stop}>
            End session
          </button>
        </div>

        <label class="form-label" for="projectTimerDescription">Current session description</label>
        <!-- A description belongs to a session, so there is nothing to write
             into until one is running. -->
        <textarea
          id="projectTimerDescription"
          class="form-control timer-description-field"
          disabled={!mineRunning}
          placeholder={mineRunning
            ? "What was done in this session..."
            : "Start a new session to add its description."}
          bind:value={description}
        ></textarea>

        <div class="project-timer-sessions mt-3">
          <h3 class="h6 mb-2">Today's sessions</h3>
          <div class="project-timer-session-list">
            {#if todays.length === 0}
              <p class="text-muted small mb-0">No sessions recorded today.</p>
            {:else}
              {#each todays as entry (entry.uid)}
                <div class="d-flex justify-content-between gap-2 small py-1 border-bottom">
                  <span>
                    {clock(entry.started_at)} – {entry.ended_at ? clock(entry.ended_at) : "running"}
                    {#if entry.description}<span class="text-muted"> · {entry.description}</span>{/if}
                  </span>
                  <span class="text-nowrap">{formatDuration(elapsedSeconds(entry, now))}</span>
                </div>
              {/each}
            {/if}
          </div>
        </div>
      </div>

      <div class="modal-footer justify-content-between">
        <span class="small text-muted">{saved}</span>
        <button
          type="button"
          class="btn btn-outline-primary btn-sm"
          disabled={!mineRunning}
          onclick={saveDescription}
        >Save description</button>
      </div>
    </div>
  </div>
</div>

<style>
  /* Bootstrap's modal needs its JavaScript to position itself; this stands in
     for the backdrop it would have created. */
  .modal-backdrop-shim {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.4);
    display: grid;
    place-items: center;
    padding: 1rem;
    z-index: 1055;
  }
  .modal-dialog { margin: 0; width: min(34rem, 100%); }
</style>

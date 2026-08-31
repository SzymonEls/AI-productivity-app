<script lang="ts">
  /**
   * Tracked time, and the timer.
   *
   * The timer used to be the server's: start and stop wrote rows, and the page
   * interpolated between polls. It is now a local row like any other, so a
   * session started on a train is still running when the train comes out of the
   * tunnel.
   */
  import { createRow, updateRow } from "../db/mutate";
  import type { LocalDatabase } from "../db/schema";
  import {
    activeEntry,
    dailyTotalsByProject,
    dayBounds,
    elapsedSeconds,
    entriesForRange,
    formatDuration,
    today,
  } from "../domain/time";
  import { live } from "../lib/live.svelte";
  import { sync } from "../sync/store.svelte";
  import type { TimeEntry } from "../sync/types";

  let { database }: { database: LocalDatabase } = $props();

  const projects = live(() => database.projects.toArray(), []);
  const entries = live(() => database.timeEntries.toArray(), []);

  let day = $state(today());
  // Ticks once a second so a running timer counts up without a round trip.
  let now = $state(new Date());
  $effect(() => {
    const timer = setInterval(() => (now = new Date()), 1000);
    return () => clearInterval(timer);
  });

  const byUid = $derived(new Map(projects.value.map((p) => [p.uid, p])));
  const active = $derived(activeEntry(entries.value));
  const bounds = $derived(dayBounds(day));
  const forDay = $derived(entriesForRange(entries.value, bounds[0], bounds[1]));
  const totals = $derived(dailyTotalsByProject(entries.value, day, now));
  const dayTotal = $derived([...totals.values()].reduce((sum, value) => sum + value, 0));

  const activeProjects = $derived(
    [...projects.value]
      .filter((project) => !project.is_archived)
      .sort((a, b) => a.title.toLowerCase().localeCompare(b.title.toLowerCase()))
  );

  function titleFor(entry: TimeEntry): string {
    const project = entry.project_uid ? byUid.get(entry.project_uid) : undefined;
    return project?.title ?? entry.project_title_snapshot ?? "Unknown project";
  }

  async function startTimer(projectUid: string) {
    // One timer at a time, exactly as the server refused a second one.
    if (active) await stopTimer();

    const project = byUid.get(projectUid);
    await createRow<TimeEntry>(database, "time_entry", {
      started_at: new Date().toISOString(),
      ended_at: null,
      description: null,
      // Written now, not when the project is deleted: it is what keeps past
      // weeks readable once the project is gone.
      project_title_snapshot: project?.title ?? null,
      project_uid: projectUid,
    });
    await after();
  }

  async function stopTimer() {
    if (!active) return;
    await updateRow<TimeEntry>(database, "time_entry", active.uid, {
      ended_at: new Date().toISOString(),
    });
    await after();
  }

  async function after() {
    await sync.refresh();
    void sync.run();
  }

  function shift(days: number) {
    const moved = new Date(`${day}T00:00:00Z`);
    moved.setUTCDate(moved.getUTCDate() + days);
    day = moved.toISOString().slice(0, 10);
  }
</script>

<section class="page">
  <header class="head">
    <h1>Time tracking</h1>
    <div class="daypick">
      <button type="button" onclick={() => shift(-1)} aria-label="Previous day">‹</button>
      <input type="date" bind:value={day} />
      <button type="button" onclick={() => shift(1)} aria-label="Next day">›</button>
    </div>
  </header>

  {#if active}
    <div class="running">
      <div>
        <span class="muted">Running</span>
        <strong>{titleFor(active)}</strong>
      </div>
      <span class="clock">{formatDuration(elapsedSeconds(active, now))}</span>
      <button type="button" class="btn" onclick={stopTimer}>Stop</button>
    </div>
  {/if}

  <h2 class="section">Start a timer</h2>
  <div class="starters">
    {#each activeProjects as project (project.uid)}
      <button
        type="button"
        class="starter"
        disabled={active?.project_uid === project.uid}
        onclick={() => startTimer(project.uid)}
      >
        {project.title}
        <span class="muted">{formatDuration(totals.get(project.uid) ?? 0)}</span>
      </button>
    {/each}
  </div>

  <h2 class="section">{day} — {formatDuration(dayTotal)} tracked</h2>
  {#if forDay.length === 0}
    <p class="muted">Nothing tracked on this day.</p>
  {:else}
    <table class="entries">
      <thead>
        <tr><th>Project</th><th>Started</th><th>Ended</th><th class="right">Length</th></tr>
      </thead>
      <tbody>
        {#each forDay as entry (entry.uid)}
          <tr>
            <td>{titleFor(entry)}</td>
            <td>{new Date(entry.started_at).toLocaleTimeString()}</td>
            <td>{entry.ended_at ? new Date(entry.ended_at).toLocaleTimeString() : "—"}</td>
            <td class="right">{formatDuration(elapsedSeconds(entry, now))}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</section>

<style>
  .page { max-width: 54rem; margin: 0 auto; padding: 1.5rem 1rem 4rem; }
  .head { display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap; }
  h1 { font-size: 1.6rem; margin: 0; }
  .section { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.06em; opacity: 0.6; margin: 2rem 0 0.6rem; }
  .muted { opacity: 0.6; }
  .daypick { display: flex; align-items: center; gap: 0.3rem; }
  .daypick button { border: 1px solid rgba(127, 127, 127, 0.3); background: transparent; color: inherit; border-radius: 0.4rem; width: 1.9rem; height: 1.9rem; cursor: pointer; }
  .daypick input { font: inherit; background: transparent; color: inherit; border: 1px solid rgba(127, 127, 127, 0.3); border-radius: 0.4rem; padding: 0.25rem 0.4rem; }

  .running { display: flex; align-items: center; gap: 1rem; margin-top: 1rem; padding: 0.75rem 1rem; border: 1px solid #16a34a; border-radius: 0.7rem; }
  .running strong { display: block; }
  .clock { margin-left: auto; font-variant-numeric: tabular-nums; font-size: 1.2rem; }
  .btn { border: 0; background: var(--bs-primary, #4f46e5); color: #fff; border-radius: 0.5rem; padding: 0.35rem 0.9rem; cursor: pointer; }

  .starters { display: grid; gap: 0.5rem; grid-template-columns: repeat(auto-fit, minmax(13rem, 1fr)); }
  .starter { display: flex; justify-content: space-between; gap: 0.75rem; border: 1px solid rgba(127, 127, 127, 0.3); background: transparent; color: inherit; border-radius: 0.6rem; padding: 0.5rem 0.7rem; cursor: pointer; font: inherit; text-align: left; }
  .starter:disabled { opacity: 0.45; cursor: default; }

  .entries { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
  .entries th { text-align: left; font-weight: 600; opacity: 0.6; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; padding-bottom: 0.3rem; }
  .entries td { padding: 0.4rem 0; border-top: 1px solid rgba(127, 127, 127, 0.15); }
  .right { text-align: right; font-variant-numeric: tabular-nums; }
</style>

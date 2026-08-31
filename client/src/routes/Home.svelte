<script lang="ts">
  /** Today's three slots, what is not scheduled, and the health ring. */
  import { updateRow } from "../db/mutate";
  import type { LocalDatabase } from "../db/schema";
  import { slotsForDate, systemHealth, unscheduledProjects, SLOTS, TIMED_SLOTS } from "../domain/slots";
  import { dailyTotalsByProject, formatDuration, today } from "../domain/time";
  import { live } from "../lib/live.svelte";
  import { BASE, link } from "../lib/router.svelte";
  import { sync } from "../sync/store.svelte";
  import type { DaySlot } from "../sync/types";

  let { database }: { database: LocalDatabase } = $props();

  const day = today();

  const projects = live(() => database.projects.toArray(), []);
  const slots = live(() => database.daySlots.toArray(), []);
  const entries = live(() => database.timeEntries.toArray(), []);

  const byUid = $derived(new Map(projects.value.map((p) => [p.uid, p])));
  const filled = $derived(slotsForDate(slots.value, day));
  const health = $derived(systemHealth(projects.value, slots.value, day));
  const unplanned = $derived(unscheduledProjects(projects.value, slots.value, day));
  const totals = $derived(dailyTotalsByProject(entries.value, day));

  async function toggleDone(slot: DaySlot) {
    await updateRow<DaySlot>(database, "day_slot", slot.uid, { is_done: !slot.is_done });
    await sync.refresh();
    void sync.run();
  }

  // The ring is a stroke-dasharray on a circle whose circumference is 100.
  const ring = $derived(`${health.percent} ${100 - health.percent}`);
  const timed = TIMED_SLOTS as readonly string[];
</script>

<section class="home">
  <div class="home-head">
    <h1>Today</h1>
    <div class="ring" data-level={health.level}>
      <svg viewBox="0 0 36 36" width="72" height="72" aria-hidden="true">
        <circle class="ring-track" cx="18" cy="18" r="15.9155" pathLength="100" />
        <circle class="ring-value" cx="18" cy="18" r="15.9155" pathLength="100"
                stroke-dasharray={ring} />
      </svg>
      <div class="ring-text">
        <strong>{health.percent}</strong>
        <span>health</span>
      </div>
    </div>
  </div>

  <p class="muted">
    {health.doneSessions} of {health.bookedSessions} booked sessions ticked off in the
    last {health.windowDays} days · {health.plannedProjects} of {health.activeProjects}
    projects have a next session
  </p>

  <div class="slots">
    {#each SLOTS as name (name)}
      {@const booking = filled[name]}
      {@const project = booking?.project_uid ? byUid.get(booking.project_uid) : undefined}
      <article class="slot" data-state={booking ? (booking.is_done ? "done" : "booked") : "free"}>
        <header>
          <span class="slot-name">{name}</span>
          {#if booking}
            <button
              type="button"
              class="tick"
              aria-pressed={booking.is_done}
              title={booking.is_done ? "Mark as not done" : "Mark this session done"}
              onclick={() => toggleDone(booking)}
            >✓</button>
          {/if}
        </header>

        {#if project}
          <h2><a href={`${BASE}/projects/${project.uid}`} use:link>{project.title}</a></h2>
          {#if project.short_goal}<p class="muted">{project.short_goal}</p>{/if}
          {#if timed.includes(name)}
            <p class="tracked">
              {formatDuration(totals.get(project.uid) ?? 0)}
              {#if project.daily_target_minutes}
                <span class="muted"> of {project.daily_target_minutes} min</span>
              {/if}
            </p>
          {/if}
        {:else if booking}
          <h2 class="muted">Unknown project</h2>
        {:else}
          <p class="muted">Free</p>
        {/if}
      </article>
    {/each}
  </div>

  <h2 class="section">Not scheduled ({unplanned.length})</h2>
  {#if unplanned.length === 0}
    <p class="muted">Everything active has a next session booked.</p>
  {:else}
    <ul class="plain">
      {#each unplanned as project (project.uid)}
        <li><a href={`${BASE}/projects/${project.uid}`} use:link>{project.title}</a></li>
      {/each}
    </ul>
  {/if}
</section>

<style>
  .home { max-width: 54rem; margin: 0 auto; padding: 1.5rem 1rem 4rem; }
  .home-head { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
  h1 { margin: 0; font-size: 1.6rem; }
  .muted { opacity: 0.65; }
  .section { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.06em; opacity: 0.6; margin-top: 2rem; }

  .ring { position: relative; width: 72px; height: 72px; }
  .ring svg { transform: rotate(-90deg); }
  .ring-track, .ring-value { fill: none; stroke-width: 3; }
  .ring-track { stroke: rgba(127, 127, 127, 0.2); }
  .ring-value { stroke: #16a34a; stroke-linecap: round; }
  [data-level="warn"] .ring-value { stroke: #d97706; }
  [data-level="bad"] .ring-value { stroke: #dc2626; }
  .ring-text { position: absolute; inset: 0; display: grid; place-content: center; text-align: center; line-height: 1; }
  .ring-text span { font-size: 0.6rem; opacity: 0.6; }

  .slots { display: grid; gap: 0.85rem; grid-template-columns: repeat(auto-fit, minmax(15rem, 1fr)); margin-top: 1.25rem; }
  .slot { border: 1px solid rgba(127, 127, 127, 0.25); border-radius: 0.85rem; padding: 0.9rem; min-height: 8rem; }
  .slot[data-state="free"] { border-style: dashed; opacity: 0.75; }
  .slot[data-state="booked"] { border-color: #d97706; }
  .slot[data-state="done"] { border-color: #16a34a; }
  .slot header { display: flex; justify-content: space-between; align-items: center; }
  .slot-name { font-weight: 700; opacity: 0.55; }
  .slot h2 { font-size: 1.05rem; margin: 0.5rem 0 0.25rem; }
  .tracked { margin: 0.5rem 0 0; font-variant-numeric: tabular-nums; }
  .tick { border: 1px solid rgba(127, 127, 127, 0.35); background: transparent; color: inherit; border-radius: 999px; width: 1.75rem; height: 1.75rem; cursor: pointer; }
  .tick[aria-pressed="true"] { background: #16a34a; border-color: #16a34a; color: #fff; }
  .plain { list-style: none; padding: 0; margin: 0.5rem 0 0; }
  .plain li { padding: 0.35rem 0; border-bottom: 1px solid rgba(127, 127, 127, 0.15); }
  a { color: inherit; text-decoration: none; }
  a:hover { text-decoration: underline; }
</style>

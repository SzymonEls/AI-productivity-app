<script lang="ts">
  /**
   * Today's three slots, what has no next session, and the health ring.
   *
   * The markup is the one from app/templates/home.html, so the stylesheet that
   * was written for it fits without a line of new CSS.
   */
  import type { LocalDatabase } from "../db/schema";
  import {
    dayProgress,
    slotCards,
    slotsForDate,
    systemHealth,
    unscheduledProjects,
  } from "../domain/slots";
  import { dailyTotalsByProject, lastSessionLabel, today } from "../domain/time";
  import { live } from "../lib/live.svelte";
  import { BASE, link } from "../lib/router.svelte";
  import Planner from "../ui/Planner.svelte";

  let { database }: { database: LocalDatabase } = $props();

  const day = today();

  const projects = live(() => database.projects.toArray(), []);
  const slots = live(() => database.daySlots.toArray(), []);
  const entries = live(() => database.timeEntries.toArray(), []);

  const byUid = $derived(new Map(projects.value.map((p) => [p.uid, p])));
  const totals = $derived(dailyTotalsByProject(entries.value, day));
  const cards = $derived(slotCards(slotsForDate(slots.value, day), byUid, totals));
  const progress = $derived(dayProgress(cards));
  const health = $derived(systemHealth(projects.value, slots.value, day));
  const unplanned = $derived(unscheduledProjects(projects.value, slots.value, day));

  const lastSessionOf = $derived.by(() => {
    const latest = new Map<string, string>();
    for (const entry of entries.value) {
      if (!entry.project_uid) continue;
      const seen = latest.get(entry.project_uid);
      if (!seen || entry.started_at > seen) latest.set(entry.project_uid, entry.started_at);
    }
    return latest;
  });

  const heading = new Intl.DateTimeFormat("en-GB", {
    weekday: "long",
    day: "2-digit",
    month: "long",
  }).format(new Date(`${day}T12:00:00Z`));

  // The planner opens in place, as it did on the server: navigating away to
  // the schedule to book one session was never what this button did.
  let planningProject = $state<{ uid: string; title: string } | null>(null);
  let fillingSlot = $state<{ date: string; slot: string } | null>(null);

</script>

<div class="dashboard-page day-slots-page">
  <section class="dashboard-section dashboard-header-section">
    <div class="d-flex justify-content-between align-items-center gap-3 flex-wrap">
      <div class="d-flex align-items-center gap-2">
        <h1 class="h5 mb-0">Today</h1>
        <span class="text-muted small">{heading}</span>
      </div>
      {#if progress}
        <div
          class="day-progress"
          title="Time tracked today against the targets of the projects in slots A and B"
        >
          <span class="day-progress-percent" class:is-complete={progress.percent >= 100}>
            {progress.percent}%
          </span>
          <span class="day-progress-detail">
            {progress.trackedLabel} / {progress.targetLabel}
          </span>
        </div>
      {/if}
    </div>
  </section>

  <div class="day-slots-layout">
    <section class="day-slots-main">
      {#each cards as card (card.slot)}
        <article
          class="slot-card slot-card-linked"
          class:slot-card-optional={!card.showsTime}
          class:slot-card-empty={!card.project}
          class:slot-card-done={card.isDone}
        >
          <div class="slot-card-letter" aria-hidden="true">{card.slot}</div>
          <div class="slot-card-body">
            {#if card.project}
              <div class="slot-card-heading">
                <!-- stretched-link makes the whole card the hit area without
                     wrapping it in an anchor, which would turn the time and the
                     badges into link text for a screen reader. -->
                <a
                  class="slot-card-title stretched-link"
                  href={`${BASE}/projects/${card.project.uid}`}
                  use:link
                >{card.project.title}</a>
                {#if card.project.is_starred}
                  <span class="switcher-badge" title="Starred" aria-hidden="true">★</span>
                {/if}
                <!-- No padlock: a private project is one nobody looking over
                     your shoulder should be able to pick out of today's three
                     cards. Privacy shows on the project's own page. -->
                {#if card.isDone}<span class="slot-done-tag">Done</span>{/if}
              </div>
              {#if card.planHeading}
                <p class="slot-card-step mb-0">{card.planHeading}</p>
              {:else}
                <p class="slot-card-step slot-card-step-empty mb-0">
                  No <code>#</code> section in the plan yet
                </p>
              {/if}
            {:else}
              <p class="slot-card-step mb-0">Nothing planned — pick a project.</p>
              <button
                type="button"
                class="slot-card-fill"
                onclick={() => (fillingSlot = { date: day, slot: card.slot })}
              >
                <span class="visually-hidden">Choose a project for slot {card.slot}</span>
              </button>
            {/if}
          </div>
          <div class="slot-card-side">
            {#if card.project && card.showsTime}
              <span class="slot-card-time">
                {card.trackedLabel}{#if card.targetLabel}&nbsp;<span
                  class="slot-card-target"
                >/ {card.targetLabel}</span>{/if}
              </span>
            {/if}
          </div>
        </article>
      {/each}
    </section>

    <aside class="day-slots-aside">
      <div class="dashboard-section">
        <h2 class="h6 mb-1">
          Not scheduled
          {#if unplanned.length}
            <span class="text-muted fw-normal">({unplanned.length})</span>
          {/if}
        </h2>
        <p class="text-muted small mb-3">No session planned after today.</p>
        {#if unplanned.length}
          <ul class="unplanned-list">
            {#each unplanned as project (project.uid)}
              <li class="unplanned-item">
                <div class="unplanned-item-text">
                  <a href={`${BASE}/projects/${project.uid}`} use:link>{project.title}</a>
                  <span class="text-muted small">
                    {lastSessionLabel(lastSessionOf.get(project.uid))}
                  </span>
                </div>
                <button
                  type="button"
                  class="btn btn-outline-secondary btn-sm"
                  onclick={() => (planningProject = { uid: project.uid, title: project.title })}
                >Plan</button>
              </li>
            {/each}
          </ul>
        {:else}
          <p class="text-muted small mb-0">Every project has a next session planned.</p>
        {/if}
      </div>

      <div class="dashboard-section system-health system-health-{health.level}">
        <h2 class="h6 mb-1">System health</h2>
        <p class="text-muted small mb-3">
          Sessions done and projects planned, over the {health.windowDays} days before today.
        </p>
        <div class="system-health-body">
          <!-- pathLength normalises the ring to 100 units, so the dash is the
               percentage itself and the radius can change freely. -->
          <div
            class="system-health-gauge"
            role="img"
            aria-label={`System health ${health.percent} out of 100`}
          >
            <svg viewBox="0 0 84 84" aria-hidden="true">
              <circle class="system-health-track" cx="42" cy="42" r="36" pathLength="100" />
              <!-- At 0 there is no arc to draw, and the round cap would leave a
                   dot on the ring that reads as a tiny score. -->
              {#if health.percent}
                <circle
                  class="system-health-value"
                  cx="42"
                  cy="42"
                  r="36"
                  pathLength="100"
                  style={`stroke-dasharray: ${health.percent} 100`}
                />
              {/if}
            </svg>
            <span class="system-health-score">{health.percent}</span>
          </div>
          <ul class="system-health-parts">
            <li>
              <span class="system-health-part-label">Sessions done</span>
              <span class="system-health-part-value">
                {health.doneSessions} / {health.bookedSessions}
              </span>
            </li>
            <li>
              <span class="system-health-part-label">Projects planned</span>
              <span class="system-health-part-value">
                {health.plannedProjects} / {health.activeProjects}
              </span>
            </li>
          </ul>
        </div>
      </div>

      <div class="dashboard-section">
        <h2 class="h6 mb-1">Tags</h2>
        <p class="text-muted small mb-3">
          Whatever you marked with a <code>#tag</code> in a plan's list.
        </p>
        <a href={`${BASE}/tags`} use:link class="btn btn-outline-secondary btn-sm">Show tags</a>
      </div>
    </aside>
  </div>
</div>

{#if planningProject}
  <Planner {database} forProject={planningProject} onclose={() => (planningProject = null)} />
{/if}

{#if fillingSlot}
  <Planner {database} forSlot={fillingSlot} onclose={() => (fillingSlot = null)} />
{/if}

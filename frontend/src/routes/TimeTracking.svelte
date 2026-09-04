<script lang="ts">
  /**
   * Tracked time, and the timer.
   *
   * The timer used to be the server's: start and stop wrote rows and the page
   * interpolated between polls. It is a local row like any other now, so a
   * session started on a train is still running when the train leaves the
   * tunnel. The filters read from the local copy, so nothing is submitted and
   * an edit saves itself - the "Show" and "Save" buttons the form had are what
   * the round trip needed, not what the page is for.
   */
  import { deleteRow, updateRow } from "../db/mutate";
  import type { LocalDatabase } from "../db/schema";
  import { minutesLabel } from "../domain/slots";
  import {
    activeEntry,
    dailyTotals,
    dailyTotalsByProject,
    dayBounds,
    elapsedSeconds,
    entriesForRange,
    formatDuration,
    overlapSeconds,
    today,
  } from "../domain/time";
  import { live } from "../lib/live.svelte";
  import { BASE, link } from "../lib/router.svelte";
  import { sync } from "../sync/store.svelte";
  import type { TimeEntry } from "../sync/types";
  import Icon from "../ui/Icon.svelte";

  let { database }: { database: LocalDatabase } = $props();

  const PIE_COLOURS = [
    "#0f9488", "#1f7ae0", "#f59e0b", "#dc3545",
    "#6f42c1", "#198754", "#0dcaf0", "#6c757d",
  ];
  /** A fortnight, the window the bar charts have always covered. */
  const CHART_DAYS = 14;
  const PER_PAGE = 50;

  const projects = live(() => database.projects.toArray(), []);
  const entries = live(() => database.timeEntries.toArray(), []);

  let day = $state(today());
  let allDates = $state(false);
  let projectFilter = $state("");
  let page = $state(1);
  // Ticks once a second so a running timer counts up without a round trip.
  let now = $state(new Date());
  $effect(() => {
    const timer = setInterval(() => (now = new Date()), 1000);
    return () => clearInterval(timer);
  });

  const byUid = $derived(new Map(projects.value.map((p) => [p.uid, p])));
  const active = $derived(activeEntry(entries.value));
  const bounds = $derived(dayBounds(day));
  const selectedProject = $derived(projectFilter ? byUid.get(projectFilter) ?? null : null);

  const matching = $derived(
    (allDates
      ? [...entries.value].sort((a, b) => b.started_at.localeCompare(a.started_at))
      : entriesForRange(entries.value, bounds[0], bounds[1])
    ).filter((entry) => !projectFilter || entry.project_uid === projectFilter)
  );

  // A page is a page of what the filters found, so changing a filter starts
  // again at the first one rather than leaving you on a page that has gone.
  $effect(() => {
    void [day, allDates, projectFilter];
    page = 1;
  });

  const pageCount = $derived(Math.max(Math.ceil(matching.length / PER_PAGE), 1));
  const shown = $derived(matching.slice((page - 1) * PER_PAGE, page * PER_PAGE));

  /** Seconds per project on the selected day - the pie, as the server built it. */
  const slices = $derived.by(() => {
    if (allDates || selectedProject) return [];
    const totals = dailyTotalsByProject(entries.value, day, now);
    return [...totals.entries()]
      .map(([uid, seconds]) => ({
        title: uid ? byUid.get(uid)?.title ?? "Unknown project" : "Unknown project",
        seconds,
      }))
      .filter((slice) => slice.seconds > 0)
      .sort((a, b) => b.seconds - a.seconds);
  });

  const dayTotal = $derived(slices.reduce((sum, slice) => sum + slice.seconds, 0));

  const pieBackground = $derived.by(() => {
    if (!dayTotal) return "";
    let position = 0;
    const stops = slices.map((slice, index) => {
      const colour = PIE_COLOURS[index % PIE_COLOURS.length];
      const start = position;
      position += (slice.seconds * 100) / dayTotal;
      return `${colour} ${start.toFixed(3)}% ${position.toFixed(3)}%`;
    });
    return `conic-gradient(${stops.join(", ")})`;
  });

  // The bars run to today rather than to the selected day: they are there to
  // show the shape of the last fortnight, which the date picker does not move.
  const recentDays = $derived(
    allDates && !selectedProject ? dailyTotals(entries.value, today(), CHART_DAYS, null, now) : []
  );
  const projectDays = $derived(
    allDates && selectedProject
      ? dailyTotals(entries.value, today(), CHART_DAYS, selectedProject.uid, now)
      : []
  );
  const projectDaySeconds = $derived(
    selectedProject && !allDates
      ? entriesForRange(entries.value, bounds[0], bounds[1], selectedProject.uid).reduce(
          (sum, entry) => sum + overlapSeconds(entry, bounds[0], bounds[1], now),
          0
        )
      : 0
  );

  const recentTotal = $derived(recentDays.reduce((sum, row) => sum + row.seconds, 0));
  const chartPeak = $derived(
    Math.max(...[...recentDays, ...projectDays].map((row) => row.seconds), 0)
  );

  const activeProjects = $derived(
    [...projects.value]
      .filter((project) => !project.is_archived)
      .sort((a, b) => a.title.toLowerCase().localeCompare(b.title.toLowerCase()))
  );

  function titleFor(entry: TimeEntry): string {
    const project = entry.project_uid ? byUid.get(entry.project_uid) : undefined;
    if (project) return project.title;
    return entry.project_title_snapshot
      ? `Unknown project (was: ${entry.project_title_snapshot})`
      : "Unknown project";
  }

  function localValue(iso: string | null): string {
    if (!iso) return "";
    const at = new Date(iso);
    const pad = (value: number) => String(value).padStart(2, "0");
    return `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}T${pad(at.getHours())}:${pad(at.getMinutes())}`;
  }

  function dayHeading(value: string): string {
    const [year, month, date] = value.split("-");
    return `${date}.${month}.${year}`;
  }

  async function after() {
    await sync.refresh();
    void sync.run();
  }

  async function stopTimer() {
    if (!active) return;
    await updateRow<TimeEntry>(database, "time_entry", active.uid, {
      ended_at: new Date().toISOString(),
    });
    await after();
  }

  async function change(entry: TimeEntry, changes: Partial<TimeEntry>) {
    await updateRow<TimeEntry>(database, "time_entry", entry.uid, changes);
    await after();
  }

  async function removeEntry(entry: TimeEntry) {
    if (!window.confirm("Delete this session?")) return;
    await deleteRow(database, "time_entry", entry.uid);
    await after();
  }

  function localToIso(value: string): string | null {
    if (!value) return null;
    const at = new Date(value);
    return Number.isNaN(at.getTime()) ? null : at.toISOString();
  }
</script>

<div class="d-flex justify-content-between align-items-start flex-wrap gap-3 mb-4">
  <div>
    <h1 class="h2 mb-1">Time tracking</h1>
    <p class="text-muted mb-0">
      Work statistics, active timer, and editing of historical sessions.
    </p>
  </div>
  {#if active}
    <!-- To the project, where the timer is: this page edits sessions, it is not
         where one is started or ended. -->
    <a
      class="btn btn-outline-success"
      href={active.project_uid
        ? `${BASE}/projects/${active.project_uid}?open_timer=1`
        : `${BASE}/time`}
      use:link
    >
      <Icon name="clock" />Active timer: {titleFor(active)} · {formatDuration(
        elapsedSeconds(active, now)
      )}
    </a>
  {/if}
</div>

<section class="card shadow-sm mb-4">
  <div class="card-body">
    <div class="row g-3 align-items-end">
      <div class="col-md-3">
        <label class="form-label" for="trackingDateMode">Date range</label>
        <select class="form-select" id="trackingDateMode" bind:value={allDates}>
          <option value={false}>Selected day</option>
          <option value={true}>All dates</option>
        </select>
      </div>
      <div class="col-md-3">
        <label class="form-label" for="trackingDate">Day</label>
        <input class="form-control" type="date" id="trackingDate" bind:value={day} disabled={allDates} />
      </div>
      <div class="col-md-4">
        <label class="form-label" for="trackingProject">Project</label>
        <select class="form-select" id="trackingProject" bind:value={projectFilter}>
          <option value="">All projects</option>
          {#each activeProjects as project (project.uid)}
            <option value={project.uid}>{project.title}</option>
          {/each}
        </select>
      </div>
      <div class="col-md-2">
        <!-- No "Show": the filters above are read straight from the local copy,
             so there is nothing to submit and nothing to wait for. -->
        <button
          class="btn btn-secondary w-100"
          type="button"
          onclick={() => {
            allDates = false;
            day = today();
            projectFilter = "";
          }}
        ><Icon name="reset" />Reset filters</button>
      </div>
    </div>
  </div>
</section>

{#if slices.length || recentDays.length || selectedProject}
  <div class="row g-4 mb-4">
    {#if slices.length}
      <div class="col-12">
        <section class="card shadow-sm h-100">
          <div class="card-body">
            <div class="d-flex justify-content-between align-items-baseline gap-3 mb-3">
              <h2 class="h5 mb-0">Selected day</h2>
              <strong>{formatDuration(dayTotal)}</strong>
            </div>
            <div class="daily-time-pie">
              <div
                class="daily-time-pie-chart"
                role="img"
                aria-label="Breakdown of work time on the selected day"
                style={`background: ${pieBackground};`}
              >
                <span>{formatDuration(dayTotal)}</span>
              </div>
              <div class="daily-time-pie-legend">
                {#each slices as slice, index}
                  <div class="daily-time-pie-item">
                    <span
                      class="daily-time-pie-swatch"
                      style={`background: ${PIE_COLOURS[index % PIE_COLOURS.length]}`}
                    ></span>
                    <span class="daily-time-pie-title" title={slice.title}>{slice.title}</span>
                    <strong>{((slice.seconds * 100) / dayTotal).toFixed(1)}%</strong>
                    <span class="text-muted">{formatDuration(slice.seconds)}</span>
                  </div>
                {/each}
              </div>
            </div>
          </div>
        </section>
      </div>
    {/if}

    {#if recentDays.length}
      <div class="col-12">
        <section class="card shadow-sm h-100">
          <div class="card-body">
            <div class="d-flex justify-content-between align-items-baseline gap-3 mb-3">
              <h2 class="h5 mb-0">Recent days</h2>
              <strong>{formatDuration(recentTotal)}</strong>
            </div>
            <div class="time-chart">
              {#each recentDays as row (row.date)}
                <div class="time-chart-row">
                  <div class="time-chart-label">{row.label}</div>
                  <div class="time-chart-track" aria-label={`${row.date}: ${row.duration}`}>
                    <div
                      class="time-chart-bar"
                      style={`width: ${chartPeak ? ((row.seconds * 100) / chartPeak).toFixed(1) : 0}%`}
                    ></div>
                  </div>
                  <div class="text-end small text-muted">{row.duration}</div>
                </div>
              {/each}
            </div>
          </div>
        </section>
      </div>
    {/if}

    {#if selectedProject}
      <div class="col-12">
        <section class="card shadow-sm h-100">
          <div class="card-body">
            <div class="d-flex justify-content-between align-items-baseline gap-3 mb-3">
              <h2 class="h5 mb-0">
                {allDates ? "Project over time" : "Project time on the selected day"}
              </h2>
              <span class="small text-muted">{selectedProject.title}</span>
            </div>
            {#if !allDates}
              <div class="time-summary-panel">
                <span class="text-muted small">{dayHeading(day)}</span>
                <strong>{formatDuration(projectDaySeconds)}</strong>
              </div>
              {#if selectedProject.daily_target_minutes}
                <p class="text-muted small mb-0 mt-2">
                  Daily target: {minutesLabel(selectedProject.daily_target_minutes)}.
                </p>
              {/if}
            {:else}
              <div class="time-chart">
                {#each projectDays as row (row.date)}
                  <div class="time-chart-row">
                    <div class="time-chart-label">{row.label}</div>
                    <div class="time-chart-track" aria-label={`${row.date}: ${row.duration}`}>
                      <div
                        class="time-chart-bar"
                        style={`width: ${chartPeak ? ((row.seconds * 100) / chartPeak).toFixed(1) : 0}%`}
                      ></div>
                    </div>
                    <div class="text-end small text-muted">{row.duration}</div>
                  </div>
                {/each}
              </div>
            {/if}
          </div>
        </section>
      </div>
    {/if}
  </div>
{/if}

<section class="card shadow-sm">
  <div class="card-body">
    <div class="mb-3">
      <h2 class="h5 mb-1">Sessions</h2>
      <p class="text-muted mb-0">
        You can edit the project, the time range and the description, or delete the entry.
      </p>
    </div>

    {#if shown.length}
      <div class="table-responsive">
        <table class="table align-middle">
          <thead>
            <tr>
              <th>Project</th><th>Start</th><th>End</th>
              <th>Duration</th><th>Description</th><th class="text-end">Actions</th>
            </tr>
          </thead>
          <tbody>
            {#each shown as entry (entry.uid)}
              <tr>
                <td>
                  <select
                    class="form-select form-select-sm"
                    aria-label="Project"
                    value={entry.project_uid ?? ""}
                    onchange={(event) =>
                      change(entry, {
                        project_uid: event.currentTarget.value || null,
                        project_title_snapshot:
                          byUid.get(event.currentTarget.value)?.title ??
                          entry.project_title_snapshot,
                      })}
                  >
                    {#if !entry.project_uid}
                      <option value="">{titleFor(entry)}</option>
                    {/if}
                    {#each activeProjects as project (project.uid)}
                      <option value={project.uid}>{project.title}</option>
                    {/each}
                  </select>
                </td>
                <td>
                  <input
                    class="form-control form-control-sm"
                    type="datetime-local"
                    value={localValue(entry.started_at)}
                    onchange={(event) => {
                      const iso = localToIso(event.currentTarget.value);
                      if (iso) change(entry, { started_at: iso });
                    }}
                  />
                </td>
                <td>
                  <input
                    class="form-control form-control-sm"
                    type="datetime-local"
                    value={localValue(entry.ended_at)}
                    onchange={(event) =>
                      change(entry, { ended_at: localToIso(event.currentTarget.value) })}
                  />
                  {#if !entry.ended_at}
                    <span class="badge text-bg-success mt-1">ongoing</span>
                  {/if}
                </td>
                <td class="text-nowrap">{formatDuration(elapsedSeconds(entry, now))}</td>
                <td>
                  <textarea
                    class="form-control form-control-sm time-entry-description"
                    rows="2"
                    value={entry.description ?? ""}
                    placeholder="What was this session?"
                    onchange={(event) =>
                      change(entry, { description: event.currentTarget.value.trim() || null })}
                  ></textarea>
                </td>
                <td class="text-end text-nowrap">
                  {#if !entry.ended_at}
                    <button type="button" class="btn btn-outline-success btn-sm" onclick={stopTimer}>
                      Stop
                    </button>
                  {/if}
                  <button
                    type="button"
                    class="btn btn-outline-danger btn-sm"
                    title="Delete this session"
                    aria-label="Delete this session"
                    onclick={() => removeEntry(entry)}
                  ><Icon name="x" /></button>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>

      {#if pageCount > 1}
        <nav
          class="d-flex justify-content-between align-items-center flex-wrap gap-2 mt-3"
          aria-label="Session pages"
        >
          <button
            type="button"
            class="btn btn-outline-secondary btn-sm"
            disabled={page <= 1}
            onclick={() => (page -= 1)}
          >Previous</button>
          <span class="small text-muted">Page {page} of {pageCount}</span>
          <button
            type="button"
            class="btn btn-outline-secondary btn-sm"
            disabled={page >= pageCount}
            onclick={() => (page += 1)}
          >Next</button>
        </nav>
      {/if}
    {:else}
      <p class="text-muted mb-0">No sessions match the selected filters.</p>
    {/if}
  </div>
</section>

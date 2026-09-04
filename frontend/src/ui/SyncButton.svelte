<script lang="ts">
  /**
   * The one place that says where things stand.
   *
   * Synchronising happens on its own, but never behind the person's back: the
   * label says what is waiting, the panel lists it in words, and offline is
   * stated plainly rather than looking like a failure.
   */
  import { describe, sync } from "../sync/store.svelte";

  let {
    titleOf,
    onresolve,
  }: { titleOf: (uid: string) => string; onresolve: () => void } = $props();

  let open = $state(false);
  let root = $state<HTMLElement | null>(null);

  // A panel that only closes by pressing the same button again is a panel that
  // gets left open; clicking away is how every other menu here behaves.
  $effect(() => {
    if (!open) return;

    function onPointerDown(event: MouseEvent) {
      if (root && !root.contains(event.target as Node)) open = false;
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") open = false;
    }

    // Captured, so a click on something that stops propagation still closes it.
    document.addEventListener("pointerdown", onPointerDown, true);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown, true);
      document.removeEventListener("keydown", onKey);
    };
  });

  const tone = $derived(
    sync.conflicts > 0
      ? "conflict"
      : sync.phase === "offline"
        ? "offline"
        : sync.pendingCount > 0
          ? "pending"
          : "clear"
  );

  function ago(iso: string | null): string {
    if (!iso) return "never";
    const seconds = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
    if (seconds < 60) return "just now";
    if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)} hr ago`;
    return `${Math.floor(seconds / 86400)} days ago`;
  }
</script>

<div class="sync" bind:this={root}>
  <button
    type="button"
    class="sync-button"
    data-tone={tone}
    aria-expanded={open}
    onclick={() => (open = !open)}
  >
    <span class="sync-dot" aria-hidden="true"></span>
    <span class="sync-label">{sync.label}</span>
  </button>

  {#if open}
    <div class="sync-panel" role="dialog" aria-label="Synchronisation">
      <div class="sync-panel-head">
        <strong>{sync.label}</strong>
        <span class="sync-muted">Last sync {ago(sync.lastSync)}</span>
      </div>

      {#if sync.phase === "offline"}
        <p class="sync-note">
          You are offline. Everything you change is saved on this device and will
          be sent by itself once there is a connection — nothing is lost.
        </p>
      {/if}

      {#if sync.message}
        <p class="sync-note sync-note-warn">{sync.message}</p>
      {/if}

      {#if sync.conflicts > 0}
        <p class="sync-note sync-note-warn">
          {sync.conflicts === 1
            ? "One change was made in two places at once and needs you to decide."
            : `${sync.conflicts} changes were made in two places at once and need you to decide.`}
        </p>
        <button
          type="button"
          class="sync-now"
          onclick={() => {
            open = false;
            onresolve();
          }}
        >Settle {sync.conflicts === 1 ? "it" : "them"}</button>
      {/if}

      {#if sync.pendingCount === 0}
        <p class="sync-note">Nothing waiting to be sent.</p>
      {:else}
        <ul class="sync-list">
          {#each sync.pending as entry (entry.id)}
            <li>
              <span>{describe(entry, titleOf)}</span>
              <span class="sync-muted">{ago(entry.changed_at)}</span>
            </li>
          {/each}
        </ul>
      {/if}

      <button
        type="button"
        class="sync-now"
        disabled={sync.phase === "working"}
        onclick={() => sync.run()}
      >
        {sync.phase === "working" ? "Syncing…" : "Sync now"}
      </button>
    </div>
  {/if}
</div>

<style>
  .sync {
    position: relative;
  }
  .sync-button {
    display: inline-flex;
    align-items: center;
    gap: 0.45rem;
    border: 1px solid var(--app-border, rgba(127, 127, 127, 0.3));
    background: transparent;
    color: inherit;
    border-radius: 999px;
    padding: 0.3rem 0.7rem;
    font-size: 0.82rem;
    cursor: pointer;
  }
  .sync-dot {
    width: 0.5rem;
    height: 0.5rem;
    border-radius: 50%;
    background: #16a34a;
  }
  [data-tone="pending"] .sync-dot { background: #d97706; }
  [data-tone="offline"] .sync-dot { background: #6b7280; }
  [data-tone="conflict"] .sync-dot { background: #dc2626; }
  [data-tone="conflict"] { border-color: #dc2626; }

  .sync-panel {
    position: absolute;
    right: 0;
    top: calc(100% + 0.5rem);
    width: min(24rem, 90vw);
    background: var(--app-surface, #fff);
    color: inherit;
    border: 1px solid var(--app-border, rgba(127, 127, 127, 0.3));
    border-radius: 0.75rem;
    box-shadow: 0 12px 32px rgba(0, 0, 0, 0.18);
    padding: 0.9rem;
    z-index: 1080;
  }
  .sync-panel-head {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 1rem;
    margin-bottom: 0.6rem;
  }
  .sync-muted { opacity: 0.6; font-size: 0.78rem; }
  .sync-note { font-size: 0.85rem; opacity: 0.8; margin: 0 0 0.6rem; }
  .sync-note-warn { color: #b45309; opacity: 1; }
  .sync-list {
    list-style: none;
    margin: 0 0 0.7rem;
    padding: 0;
    max-height: 16rem;
    overflow-y: auto;
    font-size: 0.85rem;
  }
  .sync-list li {
    display: flex;
    justify-content: space-between;
    gap: 0.75rem;
    padding: 0.35rem 0;
    border-bottom: 1px solid var(--app-border, rgba(127, 127, 127, 0.15));
  }
  .sync-list li:last-child { border-bottom: 0; }
  .sync-now {
    width: 100%;
    border: 0;
    border-radius: 0.5rem;
    padding: 0.45rem;
    background: var(--bs-primary, #4f46e5);
    color: #fff;
    cursor: pointer;
  }
  .sync-now:disabled { opacity: 0.6; cursor: default; }
</style>

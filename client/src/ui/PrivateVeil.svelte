<script lang="ts">
  /**
   * A private project's content, behind a button while safe mode is on.
   *
   * Ported from private-reveal.js, including the reasoning: a padlock on the
   * card told a room full of people which project was the private one and then
   * showed them its contents. Alone at a desk, hiding your own plan from
   * yourself is a click in the way - so the hiding belongs to safe mode, and
   * this has work to do only while that is on.
   *
   * A reveal lasts five minutes, remembered per project and per section, so
   * moving to the timer and back does not mean asking again. It is a curtain,
   * not a lock: the text is in the page all along.
   */
  import type { Snippet } from "svelte";

  let {
    projectUid,
    section,
    isPrivate,
    label = "content",
    children,
  }: {
    projectUid: string;
    section: string;
    isPrivate: boolean;
    label?: string;
    children: Snippet;
  } = $props();

  const REVEAL_MINUTES = 5;
  const key = $derived(`app-private-reveal:${projectUid}:${section}`);

  let safeMode = $state(document.documentElement.getAttribute("data-safe-mode") === "on");
  let revealedUntil = $state(0);
  let now = $state(Date.now());

  $effect(() => {
    const onChange = () => {
      safeMode = document.documentElement.getAttribute("data-safe-mode") === "on";
      // Reaching for the shield again drops every reveal.
      if (safeMode) revealedUntil = 0;
    };
    window.addEventListener("safe-mode-change", onChange);
    return () => window.removeEventListener("safe-mode-change", onChange);
  });

  $effect(() => {
    try {
      revealedUntil = Number(localStorage.getItem(key)) || 0;
    } catch {
      // Private browsing, or storage switched off: ask every time.
      revealedUntil = 0;
    }
  });

  const hidden = $derived(isPrivate && safeMode && revealedUntil <= now);

  function reveal() {
    const until = Date.now() + REVEAL_MINUTES * 60_000;
    revealedUntil = until;
    now = Date.now();
    try {
      localStorage.setItem(key, String(until));
    } catch {
      // The reveal still works for this page view.
    }
  }
</script>

{#if hidden}
  <div class="veil">
    <p class="muted">This project is private and safe mode is on.</p>
    <button type="button" class="btn" onclick={reveal}>Show {label}</button>
  </div>
{:else}
  {@render children()}
{/if}

<style>
  .veil {
    border: 1px dashed rgba(127, 127, 127, 0.4);
    border-radius: 0.75rem;
    padding: 1.5rem;
    text-align: center;
  }
  .muted { opacity: 0.65; margin: 0 0 0.75rem; }
  .btn {
    border: 1px solid rgba(127, 127, 127, 0.35);
    background: transparent;
    color: inherit;
    border-radius: 0.5rem;
    padding: 0.35rem 0.9rem;
    cursor: pointer;
  }
</style>

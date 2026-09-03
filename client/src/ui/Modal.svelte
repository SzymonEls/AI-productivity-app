<script lang="ts">
  /**
   * A Bootstrap modal, without Bootstrap's JavaScript.
   *
   * The stylesheet the application carries was written for Bootstrap's own
   * markup - a `.modal` scroll layer over a separate `.modal-backdrop`, with
   * `modal-open` on the body - so the dialog is built out of exactly that
   * rather than a lookalike. A shim with its own geometry is the reason these
   * windows stopped looking like the original.
   *
   * What Bootstrap's script did, and this does: put both layers up, hold the
   * page still behind them, close on a click outside the panel and on Escape,
   * and give the dialog focus so the keyboard is inside it.
   */
  import type { Snippet } from "svelte";

  import { dismissable } from "../lib/dismiss";

  let {
    label,
    /** Bootstrap's dialog modifiers, e.g. "modal-lg modal-dialog-scrollable". */
    dialogClass = "modal-dialog-centered",
    onclose,
    children,
  }: {
    label: string;
    dialogClass?: string;
    onclose: () => void;
    children: Snippet;
  } = $props();

  let layer = $state<HTMLDivElement | null>(null);

  $effect(() => {
    const body = document.body;
    const previousPadding = body.style.paddingRight;
    // The scrollbar goes away with the page's scrolling, and the page would
    // jump sideways by its width if nothing took its place.
    const scrollbar = window.innerWidth - document.documentElement.clientWidth;

    body.classList.add("modal-open");
    if (scrollbar > 0) body.style.paddingRight = `${scrollbar}px`;
    layer?.focus();

    return () => {
      body.classList.remove("modal-open");
      body.style.paddingRight = previousPadding;
    };
  });
</script>

<!-- display:block is what Bootstrap's script set; the class alone leaves
     .modal at display:none. -->
<div
  bind:this={layer}
  class="modal fade show"
  style="display: block"
  tabindex="-1"
  role="dialog"
  aria-modal="true"
  aria-label={label}
  use:dismissable={onclose}
>
  <div class={`modal-dialog ${dialogClass}`}>
    {@render children()}
  </div>
</div>
<div class="modal-backdrop fade show"></div>

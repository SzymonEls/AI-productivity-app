/**
 * Closing a dialog the way Bootstrap's modal did.
 *
 * The rewrite draws its own backdrops, so the two ways out that came free with
 * Bootstrap - a click on the backdrop, and Escape - have to be wired by hand.
 * Put the action on the backdrop element: a click counts only when it lands on
 * the backdrop itself, so a click inside the panel, or one that starts inside
 * and drifts out while selecting text, leaves the dialog alone.
 */
export function dismissable(node: HTMLElement, onclose: () => void) {
  let close = onclose;

  function onClick(event: MouseEvent) {
    if (event.target === node) close();
  }

  function onKey(event: KeyboardEvent) {
    if (event.key !== "Escape") return;
    // The topmost dialog takes it: anything listening further up - the project
    // switcher, a menu - must not close at the same time.
    event.stopPropagation();
    close();
  }

  node.addEventListener("click", onClick);
  document.addEventListener("keydown", onKey);

  return {
    update(next: () => void) {
      close = next;
    },
    destroy() {
      node.removeEventListener("click", onClick);
      document.removeEventListener("keydown", onKey);
    },
  };
}

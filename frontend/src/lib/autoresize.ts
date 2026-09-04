/**
 * A textarea that grows with what is typed into it.
 *
 * Carried over from the forms on the original pages, where a box that stayed
 * four rows tall meant scrolling inside a scroll to read back what you wrote.
 */
export function autoresize(node: HTMLTextAreaElement) {
  function fit() {
    node.style.height = "auto";
    node.style.height = `${node.scrollHeight}px`;
  }

  fit();
  node.addEventListener("input", fit);
  return { destroy: () => node.removeEventListener("input", fit) };
}

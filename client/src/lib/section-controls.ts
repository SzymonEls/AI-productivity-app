/**
 * The little button the original page hung on each rendered plan section.
 *
 * The renderer produces the server's markup and nothing else; the controls are
 * decoration placed on top of it afterwards, exactly as the previous frontend
 * did. Kept in one place because the plan and its archive want the same button
 * with a different arrow on it.
 */
export interface SectionControl {
  /** A FontAwesome class - the icon set the plan's own markup already uses. */
  icon: string;
  label: string;
  onpick: (index: number) => void;
}

export function sectionControls(node: HTMLElement, options: SectionControl) {
  let current = options;

  function place() {
    node.querySelectorAll(".project-markdown-section").forEach((section, index) => {
      if (section.querySelector("[data-section-control]")) return;

      const button = document.createElement("button");
      button.type = "button";
      button.className = "project-section-archive-button";
      button.dataset.sectionControl = String(index);
      button.title = current.label;
      button.setAttribute("aria-label", current.label);
      button.innerHTML = `<i class="fa-solid ${current.icon}" aria-hidden="true"></i>`;
      button.addEventListener("click", () => current.onpick(index));
      section.querySelector(".project-markdown-section-card")?.appendChild(button);
    });
  }

  place();
  // The plan is re-rendered whenever it changes, which throws the buttons away
  // with the old markup.
  const observer = new MutationObserver(place);
  observer.observe(node, { childList: true, subtree: true });

  return {
    update(next: SectionControl) {
      current = next;
    },
    destroy() {
      observer.disconnect();
    },
  };
}

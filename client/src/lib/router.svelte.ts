/**
 * Routing, by History API.
 *
 * The client owns every address now, and Flask hands the same shell back for
 * all of them, so a reload or a shared link lands where it says it does rather
 * than bouncing to the top. BASE is empty rather than removed: it keeps every
 * link in one shape, and gives one place to change if the client is ever served
 * from somewhere other than the root.
 */

export const BASE: string = "";

export type Route =
  | { name: "home" }
  | { name: "project"; uid: string }
  | { name: "schedule" }
  | { name: "archive" }
  | { name: "time" }
  | { name: "tags" }
  | { name: "archived" }
  | { name: "new" }
  | { name: "timeline" }
  | { name: "change-password" }
  | { name: "unknown"; path: string };

function parse(pathname: string): Route {
  const rest = BASE && pathname.startsWith(BASE) ? pathname.slice(BASE.length) : pathname;
  const parts = rest.split("/").filter(Boolean);

  if (parts.length === 0) return { name: "home" };
  if (parts[0] === "schedule") return { name: "schedule" };
  if (parts[0] === "archive") return { name: "archive" };
  if (parts[0] === "time") return { name: "time" };
  if (parts[0] === "tags") return { name: "tags" };
  if (parts[0] === "archived") return { name: "archived" };
  if (parts[0] === "new") return { name: "new" };
  if (parts[0] === "timeline") return { name: "timeline" };
  if (parts[0] === "change-password") return { name: "change-password" };
  if (parts[0] === "projects" && parts[1]) return { name: "project", uid: parts[1] };

  return { name: "unknown", path: rest };
}

class Router {
  current = $state<Route>(parse(window.location.pathname));

  start(): void {
    window.addEventListener("popstate", () => {
      this.current = parse(window.location.pathname);
    });
  }

  go(path: string): void {
    const target = path.startsWith("/") ? path : `${BASE}/${path}`;
    if (target !== window.location.pathname) {
      window.history.pushState({}, "", target);
    }
    this.current = parse(target);
    window.scrollTo(0, 0);
  }
}

export const router = new Router();

/** A link that routes in place instead of reloading the page. */
export function link(node: HTMLAnchorElement) {
  function onClick(event: MouseEvent) {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
    const href = node.getAttribute("href");
    // Same-origin, client-owned addresses only; anything else is a real link.
    if (!href || !href.startsWith("/") || href.startsWith("/api/")) return;
    event.preventDefault();
    router.go(href);
  }

  node.addEventListener("click", onClick);
  return { destroy: () => node.removeEventListener("click", onClick) };
}

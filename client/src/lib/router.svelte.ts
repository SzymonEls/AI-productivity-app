/**
 * Routing, by History API.
 *
 * The client is served from /app, and Flask hands the same shell back for every
 * path beneath it, so a reload or a shared link lands where it says it does
 * rather than bouncing to the top.
 */

export const BASE = "/app";

export type Route =
  | { name: "home" }
  | { name: "project"; uid: string }
  | { name: "schedule" }
  | { name: "tags" }
  | { name: "archived" }
  | { name: "unknown"; path: string };

function parse(pathname: string): Route {
  const rest = pathname.startsWith(BASE) ? pathname.slice(BASE.length) : pathname;
  const parts = rest.split("/").filter(Boolean);

  if (parts.length === 0) return { name: "home" };
  if (parts[0] === "schedule") return { name: "schedule" };
  if (parts[0] === "tags") return { name: "tags" };
  if (parts[0] === "archived") return { name: "archived" };
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
    const target = path.startsWith(BASE) ? path : `${BASE}${path}`;
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
    if (!href || !href.startsWith(BASE)) return;
    event.preventDefault();
    router.go(href);
  }

  node.addEventListener("click", onClick);
  return { destroy: () => node.removeEventListener("click", onClick) };
}

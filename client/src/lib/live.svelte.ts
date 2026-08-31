/**
 * Reading from the local copy, and re-reading when it changes.
 *
 * Dexie's liveQuery re-runs on every write to the tables it touched - including
 * writes made in another tab - so a view never has to be told to refresh after
 * a change or a sync.
 */

import { liveQuery } from "dexie";

export function live<T>(query: () => Promise<T>, initial: T) {
  let value = $state<T>(initial);
  let loaded = $state(false);

  $effect(() => {
    const subscription = liveQuery(query).subscribe({
      next: (next) => {
        value = next;
        loaded = true;
      },
      error: () => {
        loaded = true;
      },
    });
    return () => subscription.unsubscribe();
  });

  return {
    get value() {
      return value;
    },
    get loaded() {
      return loaded;
    },
  };
}

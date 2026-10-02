import { useState } from "react";

/**
 * A display choice remembered by this browser: a period, a toggle. Nothing
 * personal goes here, and the page works the same when storage is refused.
 */
export function usePreference<T extends string | boolean>(
  key: string,
  initial: T,
): [T, (value: T) => void] {
  const name = `cockpit.${key}`;
  const [value, setValue] = useState<T>(() => {
    try {
      const stored = window.localStorage.getItem(name);
      if (stored != null) {
        const parsed: unknown = JSON.parse(stored);
        if (typeof parsed === typeof initial) return parsed as T;
      }
    } catch {
      /* no storage, or an unreadable value: keep the default */
    }
    return initial;
  });
  const remember = (next: T) => {
    setValue(next);
    try {
      window.localStorage.setItem(name, JSON.stringify(next));
    } catch {
      /* the choice holds for this visit only */
    }
  };
  return [value, remember];
}

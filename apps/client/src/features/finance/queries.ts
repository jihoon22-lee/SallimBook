import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigationType } from "react-router";
import { ApiError, toApiError } from "../../platform/api";
import { useResumeRefresh } from "../../shared/useResumeRefresh";
import {
  historyEntryKey,
  rememberedListPages,
  rememberListPages,
} from "../../shared/historyRestore";

export async function allPages<T extends { id: string }>(
  read: (cursor?: string) => Promise<{ items: T[]; next_cursor: string | null }>,
): Promise<T[]> {
  const items: T[] = [];
  const seen = new Set<string>();
  let cursor: string | undefined;
  for (let page = 0; page < 100; page++) {
    const result = await read(cursor);
    for (const item of result.items) {
      if (items.some((old) => old.id === item.id)) throw new ApiError(409, "VERSION_CONFLICT");
      items.push(item);
    }
    if (!result.next_cursor) return items;
    if (seen.has(result.next_cursor)) throw new ApiError(0, "REQUEST_FAILED");
    seen.add(result.next_cursor);
    cursor = result.next_cursor;
  }
  throw new ApiError(0, "REQUEST_FAILED");
}

export function useResource<T>(read: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [checkedAt, setCheckedAt] = useState<number | null>(null);
  const generation = useRef(0);
  const reload = useCallback(async () => {
    const current = ++generation.current;
    setLoading(true);
    setError(null);
    try {
      const result = await read();
      if (generation.current === current) {
        setData(result);
        setCheckedAt(Date.now());
      }
    } catch (failure) {
      if (generation.current === current) setError(toApiError(failure));
    } finally {
      if (generation.current === current) setLoading(false);
    }
  }, [read]);
  useEffect(() => {
    // The ref is a request counter, so bumping its latest value on cleanup is intended.
    const counter = generation;
    setData(null);
    void reload();
    return () => {
      counter.current++;
    };
  }, [reload]);
  useResumeRefresh(reload, checkedAt);
  return { data, loading, error, reload, checkedAt };
}

const itemId = (item: { id: string }) => item.id;
/** Cursor pages; with `restoreAs`, a back navigation reloads as many pages as were open. */
export function usePagedList<T extends { id: string }, C extends string | number = string>(
  read: (cursor?: C) => Promise<{ items: T[]; next_cursor: C | null }>,
  keyOf: (item: T) => string = itemId,
  restoreAs?: string,
) {
  const location = useLocation();
  const navigationType = useNavigationType();
  const entry = useRef(historyEntryKey(location));
  entry.current = historyEntryKey(location);
  const restorePages = useRef(
    restoreAs !== undefined && navigationType === "POP"
      ? Math.min(rememberedListPages(entry.current, restoreAs), 10)
      : 1,
  );
  const loadedPages = useRef(0);
  const [items, setItems] = useState<T[]>([]);
  const [cursor, setCursor] = useState<C | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [checkedAt, setCheckedAt] = useState<number | null>(null);
  const generation = useRef(0);
  const load = useCallback(
    async (after?: C) => {
      const current = ++generation.current;
      setLoading(true);
      setError(null);
      try {
        const wanted = after === undefined ? restorePages.current : 1;
        let next = after;
        let pages = 0;
        let nextCursor: C | null = null;
        const fetched: T[] = [];
        const fetchedKeys = new Set<string>();
        do {
          const requested = next;
          const result = await read(requested);
          if (generation.current !== current) return;
          if (result.next_cursor !== null && result.next_cursor === requested)
            throw new ApiError(0, "REQUEST_FAILED");
          for (const item of result.items) {
            const key = keyOf(item);
            if (!fetchedKeys.has(key)) fetched.push(item);
            fetchedKeys.add(key);
          }
          nextCursor = result.next_cursor;
          pages++;
          next = result.next_cursor ?? undefined;
        } while (pages < wanted && next !== undefined);
        // Publish restored/refreshed pages together so the page never briefly shrinks
        // to its first page and clamps away the reader's current scroll position.
        setItems((old) =>
          after === undefined
            ? fetched
            : [
                ...old,
                ...fetched.filter((item) => !old.some((other) => keyOf(other) === keyOf(item))),
              ],
        );
        setCursor(nextCursor);
        // Only a finished first load spends the restore; a StrictMode re-run still gets it.
        restorePages.current = 1;
        loadedPages.current = (after === undefined ? 0 : loadedPages.current) + pages;
        setCheckedAt(Date.now());
        if (restoreAs !== undefined)
          rememberListPages(entry.current, restoreAs, loadedPages.current);
      } catch (failure) {
        if (generation.current === current) setError(toApiError(failure));
      } finally {
        if (generation.current === current) setLoading(false);
      }
    },
    [read, keyOf, restoreAs],
  );
  useEffect(() => {
    // The ref is a request counter, so bumping its latest value on cleanup is intended.
    const counter = generation;
    setItems([]);
    setCursor(null);
    void load();
    return () => {
      counter.current++;
    };
  }, [load]);
  const reload = useCallback(() => {
    restorePages.current = 1;
    return load();
  }, [load]);
  const refreshVisible = useCallback(() => {
    restorePages.current = Math.max(loadedPages.current, 1);
    return load();
  }, [load]);
  useResumeRefresh(refreshVisible, checkedAt);
  return {
    items,
    cursor,
    loading,
    error,
    reload,
    checkedAt,
    more: () => (cursor === null ? Promise.resolve() : load(cursor)),
  };
}

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, toApiError } from "../../platform/api";

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
  const generation = useRef(0);
  const reload = useCallback(async () => {
    const current = ++generation.current;
    setLoading(true);
    setError(null);
    try {
      const result = await read();
      if (generation.current === current) setData(result);
    } catch (failure) {
      if (generation.current === current) setError(toApiError(failure));
    } finally {
      if (generation.current === current) setLoading(false);
    }
  }, [read]);
  useEffect(() => {
    setData(null);
    void reload();
    return () => {
      generation.current++;
    };
  }, [reload]);
  return { data, loading, error, reload };
}

const itemId = (item: { id: string }) => item.id;
export function usePagedList<T extends { id: string }, C extends string | number = string>(
  read: (cursor?: C) => Promise<{ items: T[]; next_cursor: C | null }>,
  keyOf: (item: T) => string = itemId,
) {
  const [items, setItems] = useState<T[]>([]);
  const [cursor, setCursor] = useState<C | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const generation = useRef(0);
  const load = useCallback(
    async (after?: C) => {
      const current = ++generation.current;
      setLoading(true);
      setError(null);
      if (after === undefined) {
        setItems([]);
        setCursor(null);
      }
      try {
        const result = await read(after);
        if (generation.current !== current) return;
        if (result.next_cursor !== null && result.next_cursor === after)
          throw new ApiError(0, "REQUEST_FAILED");
        setItems((old) =>
          after === undefined
            ? result.items
            : [
                ...old,
                ...result.items.filter(
                  (item) => !old.some((other) => keyOf(other) === keyOf(item)),
                ),
              ],
        );
        setCursor(result.next_cursor);
      } catch (failure) {
        if (generation.current === current) setError(toApiError(failure));
      } finally {
        if (generation.current === current) setLoading(false);
      }
    },
    [read, keyOf],
  );
  useEffect(() => {
    void load();
    return () => {
      generation.current++;
    };
  }, [load]);
  return {
    items,
    cursor,
    loading,
    error,
    reload: () => load(),
    more: () => (cursor === null ? Promise.resolve() : load(cursor)),
  };
}

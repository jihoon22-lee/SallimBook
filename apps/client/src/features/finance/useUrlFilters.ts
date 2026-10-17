import { useEffect, useRef } from "react";
import { useSearchParams } from "react-router";
export function useUrlFilters() {
  const [params, setParams] = useSearchParams(); const pending = useRef(params); useEffect(() => { pending.current = params; }, [params]);
  return { params, filter: (key: string, value: string) => { const next = new URLSearchParams(pending.current); if (value) next.set(key, value); else next.delete(key); pending.current = next; setParams(next); }, reset: () => { pending.current = new URLSearchParams(); setParams({}); } };
}

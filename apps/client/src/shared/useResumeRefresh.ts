import { useEffect } from "react";
import { observeAppResume } from "../platform/appLifecycle";
import { useHasUnsavedChanges } from "./UnsavedChanges";

const STALE_AFTER_MS = 120_000;

/** Revalidate reads only; a draft remains on its reviewed version until explicitly saved. */
export function useResumeRefresh(reload: () => Promise<void>, checkedAt: number | null) {
  const hasUnsavedChanges = useHasUnsavedChanges();
  useEffect(() => {
    let pending = false;
    let attemptedAt = checkedAt ?? Date.now();
    return observeAppResume(() => {
      const now = Date.now();
      if (pending || hasUnsavedChanges() || now - attemptedAt < STALE_AFTER_MS) return;
      pending = true;
      attemptedAt = now;
      void reload()
        .catch(() => undefined)
        .finally(() => {
          pending = false;
        });
    });
  }, [reload, checkedAt, hasUnsavedChanges]);
}

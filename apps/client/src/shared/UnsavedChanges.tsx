import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";
import { useBlocker } from "react-router";
import type { BlockerFunction } from "react-router";

const DEFAULT_MESSAGE = "이 화면을 나가면 입력한 내용이 사라져요.";

type Entry = { dirty: boolean; message: string };
type Registry = {
  register: (id: symbol, entry: Entry) => void;
  unregister: (id: symbol) => void;
  release: (id: symbol) => void;
  open: boolean;
  stay: () => void;
};

// Outside the provider (e.g. a MemoryRouter test harness) guards do nothing.
const UnsavedChangesContext = createContext<Registry>({
  register: () => {},
  unregister: () => {},
  release: () => {},
  open: false,
  stay: () => {},
});

/** The app's one navigation blocker; forms only report whether they hold unsaved input. */
export function UnsavedChangesProvider({ children }: { children: ReactNode }) {
  const entries = useRef(new Map<symbol, Entry>());
  const [dirtyCount, setDirtyCount] = useState(0);
  const recount = useCallback(
    () => setDirtyCount([...entries.current.values()].filter((entry) => entry.dirty).length),
    [],
  );
  const hasDirty = useCallback(
    () => [...entries.current.values()].some((entry) => entry.dirty),
    [],
  );
  const blocker = useBlocker(
    useCallback<BlockerFunction>(
      ({ currentLocation, nextLocation }) =>
        hasDirty() &&
        (currentLocation.pathname !== nextLocation.pathname ||
          currentLocation.search !== nextLocation.search),
      [hasDirty],
    ),
  );
  const open = blocker.state === "blocked";
  const lastField = useRef<HTMLElement | null>(null);
  useEffect(() => {
    const track = (event: FocusEvent) => {
      const target = event.target;
      if (target instanceof HTMLElement && target.matches("input, textarea, select"))
        lastField.current = target;
    };
    document.addEventListener("focusin", track);
    return () => document.removeEventListener("focusin", track);
  }, []);
  // undefined: nothing to refocus; null: refocus the main form's first field.
  const refocus = useRef<HTMLElement | null | undefined>(undefined);
  const stay = useCallback(() => {
    refocus.current = lastField.current;
    blocker.reset?.();
  }, [blocker]);
  // Runs after the dialog's own cleanup has closed it, so closing cannot take the focus back.
  useEffect(() => {
    if (open || refocus.current === undefined) return;
    const last = refocus.current;
    refocus.current = undefined;
    focusFormField(last);
  }, [open]);
  const leave = useCallback(() => {
    // The person chose to discard; the left screen's guards must not block a quick next
    // navigation (e.g. back) before their unmount cleanup runs.
    for (const entry of entries.current.values()) entry.dirty = false;
    recount();
    blocker.proceed?.();
  }, [blocker, recount]);

  useEffect(() => {
    if (!dirtyCount) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirtyCount]);

  const register = useCallback(
    (id: symbol, entry: Entry) => {
      entries.current.set(id, entry);
      recount();
    },
    [recount],
  );
  const unregister = useCallback(
    (id: symbol) => {
      entries.current.delete(id);
      recount();
    },
    [recount],
  );
  const release = useCallback(
    (id: symbol) => {
      const entry = entries.current.get(id);
      // Synchronous, so a navigate() in the same tick after a save is not blocked.
      if (entry) entry.dirty = false;
      recount();
    },
    [recount],
  );
  const registry = useMemo<Registry>(
    () => ({ register, unregister, release, open, stay }),
    [register, unregister, release, open, stay],
  );
  const message =
    [...entries.current.values()].find((entry) => entry.dirty)?.message ?? DEFAULT_MESSAGE;

  return (
    <UnsavedChangesContext.Provider value={registry}>
      {children}
      {open && <LeaveDialog message={message} stay={stay} leave={leave} />}
    </UnsavedChangesContext.Provider>
  );
}

/**
 * After "keep editing" the person lands on the first field of the form they were in. The
 * dialog gives focus back to what opened it when it closes, so this waits until it is gone.
 */
function focusFormField(last: HTMLElement | null) {
  window.requestAnimationFrame(() =>
    window.requestAnimationFrame(() => {
      const form =
        (last?.isConnected ? last.closest("form") : null) ?? document.querySelector("main form");
      form
        ?.querySelector<HTMLElement>(
          "input:not([type=hidden]):not(:disabled), textarea:not(:disabled), select:not(:disabled)",
        )
        ?.focus({ preventScroll: true });
    }),
  );
}

function LeaveDialog({
  message,
  stay,
  leave,
}: {
  message: string;
  stay: () => void;
  leave: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const stayRef = useRef<HTMLButtonElement>(null);
  const id = useId();
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (!dialog.open) dialog.showModal();
    stayRef.current?.focus();
    return () => {
      if (dialog.open) dialog.close();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      className="leave-dialog"
      role="alertdialog"
      aria-labelledby={`${id}-title`}
      aria-describedby={`${id}-message`}
      onCancel={(event) => {
        event.preventDefault();
        stay();
      }}
    >
      <h2 id={`${id}-title`}>저장하지 않은 입력이 있어요</h2>
      <p id={`${id}-message`}>{message}</p>
      <div className="form-actions">
        <button ref={stayRef} type="button" onClick={stay}>
          계속 입력하기
        </button>
        <button type="button" className="secondary-button" onClick={leave}>
          입력 버리고 나가기
        </button>
      </div>
    </dialog>
  );
}

/** Register this form's unsaved state; `release()` clears it before a programmatic leave. */
export function useUnsavedChangesGuard(dirty: boolean, message = DEFAULT_MESSAGE) {
  const { register, unregister, release } = useContext(UnsavedChangesContext);
  const [id] = useState(() => Symbol("unsaved-changes"));
  useEffect(() => {
    register(id, { dirty, message });
  }, [register, id, dirty, message]);
  useEffect(() => () => unregister(id), [unregister, id]);
  return useMemo(() => ({ release: () => release(id) }), [release, id]);
}

export function useLeavePrompt() {
  const { open, stay } = useContext(UnsavedChangesContext);
  return useMemo(() => ({ open, stay }), [open, stay]);
}

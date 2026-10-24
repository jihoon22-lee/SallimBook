import { createContext, useCallback, useContext, useEffect, useId, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Icon } from "./Icon";
import { useUnsavedChangesGuard } from "./UnsavedChanges";

const TaskPanelRelease = createContext<() => void>(() => {});

/** Keep optional search controls out of the path to the records themselves. */
export function FilterPanel({
  title,
  activeCount = 0,
  defaultLabel = "추가 조건 없음",
  children,
}: {
  title: string;
  activeCount?: number;
  defaultLabel?: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    if (open && !dialog.current?.open) dialog.current?.showModal();
  }, [open]);
  return (
    <details
      className="filter-panel"
      open={open}
      onToggle={(event) => {
        // A dialog also emits toggle; only the disclosure owns this state.
        if (event.target === event.currentTarget) setOpen(event.currentTarget.open);
      }}
    >
      <summary>
        <span>
          <Icon name="filter" size={18} />
          {title}
        </span>
        <span className="filter-indicator">
          {activeCount ? `조건 ${activeCount}개 적용` : defaultLabel}
          <span aria-hidden="true">{open ? "−" : "+"}</span>
        </span>
      </summary>
      <dialog
        ref={dialog}
        className="filter-dialog"
        data-filter-dialog
        aria-labelledby={titleId}
        onClose={() => {
          // A queued close event must not close a dialog that has already reopened.
          if (!dialog.current?.open) setOpen(false);
        }}
      >
        <div className="section-title">
          <h2 id={titleId}>{title}</h2>
          <button
            type="button"
            onClick={() => {
              // Keep the disclosure in sync in this interaction; the native close event
              // is queued and can otherwise leave a stale, apparently open disclosure.
              setOpen(false);
              dialog.current?.close();
            }}
          >
            필터 닫기
          </button>
        </div>
        <div className="filter-panel-body">{children}</div>
      </dialog>
    </details>
  );
}

/** A newly opened inline task must be discoverable without searching below the fold. */
export function TaskPanel({ label, children }: { label: string; children: ReactNode }) {
  const ref = useRef<HTMLElement>(null);
  const [dirty, setDirty] = useState(false);
  const guard = useUnsavedChangesGuard(dirty);
  // A saved panel holds nothing unsaved until the next edit, even though it stays on screen.
  const release = useCallback(() => {
    guard.release();
    setDirty(false);
  }, [guard]);
  useEffect(() => {
    const opener = document.activeElement;
    ref.current?.focus({ preventScroll: true });
    ref.current?.scrollIntoView({ block: "start" });
    return () => {
      if (opener instanceof HTMLElement && opener.isConnected)
        opener.focus({ preventScroll: true });
    };
  }, []);
  return (
    <TaskPanelRelease.Provider value={release}>
      <section
        ref={ref}
        className="task-panel"
        aria-label={label}
        tabIndex={-1}
        onInput={() => setDirty(true)}
      >
        {children}
      </section>
    </TaskPanelRelease.Provider>
  );
}

/** Clear the enclosing task panel's unsaved state before a save navigates away. */
export function useTaskPanelRelease(): () => void {
  return useContext(TaskPanelRelease);
}

export function TaskNotice({ message }: { message: string }) {
  const ref = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    if (!message) return;
    ref.current?.focus({ preventScroll: true });
    ref.current?.scrollIntoView({ block: "nearest" });
  }, [message]);
  return message ? (
    <p ref={ref} className="task-success" role="status" tabIndex={-1}>
      {message}
    </p>
  ) : null;
}

export function TaskNavigation({
  label,
  sections,
}: {
  label: string;
  sections: { id: string; label: string; detail: string }[];
}) {
  return (
    <nav className="task-navigation" aria-label={label}>
      {sections.map((section, index) => (
        <a
          key={section.id}
          href={`#${section.id}`}
          onClick={(event) => {
            const target = document.getElementById(section.id);
            if (!target) return;
            event.preventDefault();
            target.focus({ preventScroll: true });
            target.scrollIntoView({ block: "start" });
          }}
        >
          <span className="task-step" aria-hidden="true">
            {index + 1}
          </span>
          <span>
            <strong>{section.label}</strong>
            <small>{section.detail}</small>
          </span>
          <Icon name="arrow-right" size={16} />
        </a>
      ))}
    </nav>
  );
}

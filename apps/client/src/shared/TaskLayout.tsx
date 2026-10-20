import { createContext, useContext, useEffect, useRef, useState } from "react";
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
  const [open, setOpen] = useState(activeCount > 0);
  return (
    <details
      className="filter-panel"
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
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
      <div className="filter-panel-body">{children}</div>
    </details>
  );
}

/** A newly opened inline task must be discoverable without searching below the fold. */
export function TaskPanel({ label, children }: { label: string; children: ReactNode }) {
  const ref = useRef<HTMLElement>(null);
  const [dirty, setDirty] = useState(false);
  const guard = useUnsavedChangesGuard(dirty);
  useEffect(() => {
    ref.current?.focus({ preventScroll: true });
    ref.current?.scrollIntoView({ block: "start" });
  }, []);
  return (
    <TaskPanelRelease.Provider value={guard.release}>
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

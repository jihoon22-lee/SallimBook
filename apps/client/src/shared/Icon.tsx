import type { CSSProperties } from "react";

export type IconName =
  | "home"
  | "assets"
  | "cashflow"
  | "insurance"
  | "more"
  | "settings"
  | "account"
  | "arrow-left"
  | "arrow-right"
  | "arrow-up-right"
  | "calendar"
  | "package"
  | "check"
  | "plus"
  | "book"
  | "filter"
  | "refresh";

/** Small, original line drawings. Decorative: the containing control supplies its name. */
export function Icon({
  name,
  size = 20,
  className,
  style,
}: {
  name: IconName;
  size?: number;
  className?: string;
  style?: CSSProperties;
}) {
  const drawing = {
    home: (
      <>
        <path d="m3 10 9-7 9 7" />
        <path d="M5 9v11h5v-6h4v6h5V9" />
      </>
    ),
    assets: (
      <>
        <path d="M4 20V9h4v11M10 20V4h4v16M16 20v-8h4v8M3 20h18" />
      </>
    ),
    cashflow: (
      <>
        <path d="M4 7h15m-4-4 4 4-4 4M20 17H5m4-4-4 4 4 4" />
      </>
    ),
    insurance: (
      <>
        <path d="M12 3 4 6v6c0 4 4 7 8 9 4-2 8-5 8-9V6z" />
        <path d="M8 12h8m-4-4v8" />
      </>
    ),
    more: (
      <>
        <circle cx="5" cy="12" r="1" />
        <circle cx="12" cy="12" r="1" />
        <circle cx="19" cy="12" r="1" />
      </>
    ),
    settings: (
      <>
        <path d="M4 7h16M4 17h16" />
        <circle cx="8" cy="7" r="3" fill="var(--surface)" />
        <circle cx="16" cy="17" r="3" fill="var(--surface)" />
      </>
    ),
    account: (
      <>
        <circle cx="12" cy="8" r="4" />
        <path d="M4 21v-2a8 8 0 0 1 16 0v2" />
      </>
    ),
    "arrow-left": <path d="m10 5-7 7 7 7M3 12h18" />,
    "arrow-right": <path d="m14 5 7 7-7 7M3 12h18" />,
    "arrow-up-right": <path d="M6 18 18 6M7 6h11v11" />,
    calendar: (
      <>
        <rect x="3" y="5" width="18" height="16" rx="3" />
        <path d="M7 3v4m10-4v4M3 11h18m-14 4h3m4 0h3" />
      </>
    ),
    package: (
      <>
        <path d="m3 7 9-4 9 4v11l-9 4-9-4zM3 7l9 4 9-4M12 11v11M7 5l9 4" />
      </>
    ),
    check: <path d="m5 12 4 4L19 6" />,
    plus: <path d="M12 4v16M4 12h16" />,
    book: (
      <>
        <path d="M12 6C9 3 5 3 3 4v15c3-1 6-1 9 2 3-3 6-3 9-2V4c-2-1-6-1-9 2Z" />
        <path d="M12 6v15M6 8l3 1M6 12l3 1m6-4 3-1m-3 5 3-1" />
      </>
    ),
    filter: (
      <>
        <path d="M4 5h16M7 12h10M10 19h4" />
        <circle cx="8" cy="5" r="1" />
        <circle cx="15" cy="12" r="1" />
      </>
    ),
    refresh: (
      <>
        <path d="M20 10a8 8 0 0 0-14-5L3 8m0-5v5h5M4 14a8 8 0 0 0 14 5l3-3m0 5v-5h-5" />
      </>
    ),
  }[name];
  return (
    <svg
      className={className ? `icon ${className}` : "icon"}
      style={style}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {drawing}
    </svg>
  );
}

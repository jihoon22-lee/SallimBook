import type { ReactNode } from "react";
import { Link, useLocation } from "react-router";

/** A /login link that brings the person back to this screen after signing in again. */
export function ReturnLoginLink({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  const location = useLocation();
  return (
    <Link
      className={className}
      to="/login"
      state={{ from: location.pathname + location.search + location.hash }}
    >
      {children}
    </Link>
  );
}

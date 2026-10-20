const ORIGIN = "https://app.invalid";

/** Accept only a same-app path to return to after login; anything else is dropped. */
export function safeReturnPath(value: unknown): string | null {
  if (typeof value !== "string" || value.length < 1 || value.length > 2048) return null;
  if (!value.startsWith("/") || value.startsWith("//") || value.startsWith("/\\")) return null;
  // eslint-disable-next-line no-control-regex -- control characters are exactly what this rejects.
  if (/[\u0000-\u001f\u007f\\]/.test(value)) return null;
  const url = new URL(value, ORIGIN);
  if (url.origin !== ORIGIN) return null;
  if (url.pathname === "/login" || url.pathname.startsWith("/login/")) return null;
  return url.pathname + url.search + url.hash;
}

/** Smooth scrolling unless the person asked the system for reduced motion. */
export function scrollBehavior(): ScrollBehavior {
  return matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
}

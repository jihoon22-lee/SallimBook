/**
 * A form that disables its fields while it saves drops the focus of the field or button the
 * person was on (Enter in a field, or the save button). Remember it before the request and
 * hand it back once the form is enabled again; a screen that moved on keeps its own focus.
 * React re-enables the fieldset a little after the request settles, so the hand-back waits a
 * few frames for that instead of giving up while the field is still disabled.
 */
const MAX_FRAMES = 30;

export function rememberFocus(): () => void {
  const active = document.activeElement;
  if (!(active instanceof HTMLElement) || !active.closest("form")) return () => {};
  return () => {
    let frames = 0;
    const attempt = () => {
      const lost = !document.activeElement || document.activeElement === document.body;
      if (!lost || !active.isConnected) return;
      if (active.matches(":disabled")) {
        if (++frames < MAX_FRAMES) requestAnimationFrame(attempt);
        return;
      }
      active.focus({ preventScroll: true });
    };
    window.setTimeout(attempt, 0);
  };
}

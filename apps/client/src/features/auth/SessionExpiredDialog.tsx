import { useEffect, useId, useRef } from "react";
import { useLocation } from "react-router";
import { useAuth } from "./AuthProvider";
import { LoginForm } from "./LoginPage";

/**
 * Shown when a save finds the session ended. The screen behind it stays mounted, so what was
 * typed stays in memory only; after signing in the person presses save again.
 */
export function SessionExpiredDialog() {
  const { expiry, dismissExpiry, endExpiry } = useAuth();
  const { pathname } = useLocation();
  const keptOn = useRef<string | null>(null);
  useEffect(() => {
    if (!expiry) keptOn.current = null;
    else if (keptOn.current === null) keptOn.current = pathname;
    // A form that outlived its session is only kept while the person stays on that screen.
    else if (keptOn.current !== pathname) endExpiry();
  }, [expiry, pathname, endExpiry]);
  return expiry === "prompt" ? <SignInDialog close={dismissExpiry} /> : null;
}

function SignInDialog({ close }: { close: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const id = useId();
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (!dialog.open) dialog.showModal();
    return () => {
      if (dialog.open) dialog.close();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      className="leave-dialog session-dialog"
      aria-labelledby={`${id}-title`}
      aria-describedby={`${id}-message`}
      onCancel={(event) => {
        event.preventDefault();
        close();
      }}
    >
      <h2 id={`${id}-title`}>로그인이 만료되었어요</h2>
      <p id={`${id}-message`}>
        입력한 내용은 이 화면에 그대로 있어요. 다시 로그인한 뒤 저장을 한 번 더 눌러 주세요.
      </p>
      <LoginForm expired onSignedIn={() => {}} />
      <div className="form-actions">
        <button type="button" className="secondary-button" onClick={close}>
          닫기
        </button>
      </div>
    </dialog>
  );
}

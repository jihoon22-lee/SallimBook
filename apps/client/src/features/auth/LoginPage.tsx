import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import type { components } from "@sallimbook/api-client";
import { ApiError, toApiError } from "../../platform/api";
import { isNativeAuth } from "../../platform/nativeAuth";
import { NativeAuthAction } from "./NativeAuthAction";
import { AuthError, clearSensitiveFields, SessionStatus, useMounted, useSensitiveForm } from "./AuthFeedback";
import { useAuth } from "./AuthProvider";

function LoginForm() {
  const { state, login } = useAuth();
  const navigate = useNavigate();
  const formRef = useSensitiveForm();
  const mounted = useMounted();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const form = event.currentTarget;
    const fields = new FormData(form);
    const input: components["schemas"]["LoginRequest"] = {
      login_name: String(fields.get("login_name") ?? ""),
      password: String(fields.get("password") ?? ""),
      device_label: String(fields.get("device_label") ?? ""),
    };
    clearSensitiveFields(form);
    setError(null);
    setBusy(true);
    try {
      await login(input);
      if (mounted.current) navigate("/settings/auth", { replace: true });
    } catch (failure) {
      if (mounted.current) setError(toApiError(failure));
    } finally {
      if (mounted.current) setBusy(false);
    }
  }

  return <section className="card">
    {state.status === "authenticated" && <p>{state.member.display_name} 님으로 로그인되어 있어요. 아래에서 다시 로그인하면 최근 인증을 확인할 수 있어요.</p>}
    <form ref={formRef} className="auth-form" onSubmit={(event) => void submit(event)}>
      <div className="form-field"><label htmlFor="login-name">로그인 이름</label>
        <input id="login-name" name="login_name" autoComplete="username" autoCapitalize="none" spellCheck={false} required minLength={3} maxLength={64} pattern="[a-zA-Z][a-zA-Z0-9_.\-]{2,63}" disabled={busy} />
      </div>
      <div className="form-field"><label htmlFor="login-password">비밀번호</label>
        <input id="login-password" name="password" type="password" autoComplete="current-password" required maxLength={128} disabled={busy} />
      </div>
      <div className="form-field"><label htmlFor="login-device">이 기기 이름</label>
        <input id="login-device" name="device_label" autoComplete="off" required maxLength={80} defaultValue="웹 브라우저" disabled={busy} aria-describedby="login-device-help" />
        <p id="login-device-help" className="muted">등록 기기 목록에서 알아볼 수 있는 이름을 적어 주세요.</p>
      </div>
      <AuthError error={error} login />
      <button type="submit" disabled={busy}>{busy ? "로그인 중…" : "로그인"}</button>
    </form>
    <p className="muted">패스키 로그인은 준비 중이에요.</p>
    <Link to="/onboarding">초대 코드로 계정 등록</Link>
  </section>;
}

export function LoginPage() {
  const { state } = useAuth();
  return <>
    <div className="intro"><p className="eyebrow">우리 집의 기록</p><h1>로그인</h1><p>각자의 계정으로 하나의 공동 가계를 사용해요.</p></div>
    {state.status === "signed-out" && state.remoteRevocationUnconfirmed && <p role="status">이 기기에서는 로그아웃했어요. 서버 연결을 확인하지 못해 다른 기기에서 이 기기의 연결 해제를 확인해 주세요.</p>}
    {state.status === "signed-out" || state.status === "authenticated" ? isNativeAuth() ? <NativeAuthAction mode="login" /> : <LoginForm /> : <SessionStatus />}
  </>;
}

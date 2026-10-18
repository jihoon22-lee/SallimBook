import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import type { components } from "@sallimbook/api-client";
import { toApiError } from "../../platform/api";
import type { ApiError } from "../../platform/api";
import { isNativeAuth } from "../../platform/nativeAuth";
import { AuthError, clearSensitiveFields, SessionStatus, useMounted, useSensitiveForm } from "./AuthFeedback";
import { useAuth } from "./AuthProvider";
import { useAuthCeremony } from "./useAuthCeremony";
import { useSetupAvailability } from "./OnboardingEntry";

type Mode = "setup" | "connect";

function RegistrationForm({ mode }: { mode: Mode }) {
  const { createHousehold, connectHousehold } = useAuth();
  const navigate = useNavigate();
  const formRef = useSensitiveForm();
  const mounted = useMounted();
  const ceremony = useAuthCeremony();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [validation, setValidation] = useState("");
  const setup = mode === "setup";
  const unavailable = error?.code === "SETUP_COMPLETE" || error?.code === "SETUP_UNAVAILABLE";

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || unavailable) return;
    const form = event.currentTarget;
    const fields = new FormData(form);
    const input: components["schemas"]["SetupRequest"] = {
      display_name: String(fields.get("display_name") ?? "").trim(),
      password: String(fields.get("password") ?? ""), device_label: "웹 브라우저",
    };
    const code = String(fields.get("code") ?? "");
    const matches = input.password === fields.get("password_confirmation");
    clearSensitiveFields(form);
    setError(null); setValidation("");
    if (!matches) { setValidation("비밀번호 확인이 일치하지 않아요. 다시 입력해 주세요."); return; }
    if (!input.display_name) { setValidation("함께 사용할 이름을 입력해 주세요."); return; }
    setBusy(true);
    try {
      await ceremony.run((signal) => setup ? createHousehold(input, signal) : connectHousehold({ ...input, code }, signal));
      if (mounted.current) navigate("/", { replace: true });
    } catch (failure) { if (mounted.current) setError(toApiError(failure)); }
    finally { if (mounted.current) setBusy(false); }
  }

  return <section className="card" aria-labelledby="registration-title">
    <h2 id="registration-title">{setup ? "우리 가계 시작하기" : "배우자 연결"}</h2>
    <p>{setup ? "내 계정을 만들고 둘이 사용할 가계를 시작해요." : "배우자가 만든 8자리 연결 코드로 같은 가계에 참여해요."}</p>
    <p className="muted">다음 로그인 이름은 <strong>{setup ? "owner" : "partner"}</strong>예요. 등록을 마치면 바로 로그인돼요.</p>
    <form ref={formRef} className="auth-form" onSubmit={(event) => void submit(event)}>
      {!setup && <div className="form-field"><label htmlFor="connection-code">배우자 연결 코드</label>
        <input id="connection-code" name="code" type="password" inputMode="numeric" autoComplete="off" required minLength={8} maxLength={8} pattern="[0-9]{8}" disabled={busy} aria-describedby="connection-code-help" />
        <p id="connection-code-help" className="muted">앞자리 0을 포함해 숫자 8자리를 그대로 입력해 주세요.</p>
      </div>}
      <div className="form-field"><label htmlFor="registration-name">표시 이름</label>
        <input id="registration-name" name="display_name" autoComplete="nickname" required maxLength={80} disabled={busy || unavailable} />
      </div>
      <div className="form-field"><label htmlFor="registration-password">새 비밀번호</label>
        <input id="registration-password" name="password" type="password" autoComplete="new-password" required minLength={15} maxLength={128} disabled={busy || unavailable} aria-describedby="registration-password-help" />
        <p id="registration-password-help" className="muted">15자 이상, 128자 이하로 입력해 주세요.</p>
      </div>
      <div className="form-field"><label htmlFor="registration-confirmation">새 비밀번호 확인</label>
        <input id="registration-confirmation" name="password_confirmation" type="password" autoComplete="new-password" required minLength={15} maxLength={128} disabled={busy || unavailable} />
      </div>
      {validation && <p role="alert">{validation}</p>}
      {error?.code === "REQUEST_CANCELLED" ? <p role="alert">등록 요청 대기를 중단했어요. 등록이 끝났을 수 있으니 로그인 상태를 확인한 뒤 다시 진행해 주세요.</p> : error?.code === "LOGIN_UNAVAILABLE" ? <p role="alert">이 방식으로 계정을 등록할 수 없어요. <Link to="/onboarding/invitation">이전에 받은 초대 코드로 등록</Link>하거나 기존 계정으로 로그인해 주세요.</p> : <AuthError error={error} />}
      <button type="submit" disabled={busy || unavailable}>{busy ? "등록 중…" : setup ? "가계 만들고 시작하기" : "연결하고 시작하기"}</button>
      {busy && <button type="button" onClick={ceremony.cancel}>요청 대기 중단</button>}
    </form>
    <p><Link to="/login">이미 계정이 있어요 · 로그인</Link></p>
    {setup && <Link to="/onboarding/connect">배우자 연결 코드가 있어요</Link>}
  </section>;
}

function NativeRegistration({ mode }: { mode: Mode }) {
  const { registerNative, reloadSession } = useAuth();
  const mounted = useMounted(); const navigate = useNavigate();
  const [busy, setBusy] = useState(false), [cancelled, setCancelled] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const unavailable = error?.code === "SETUP_COMPLETE" || error?.code === "SETUP_UNAVAILABLE";
  async function start() {
    if (busy || unavailable) return;
    setBusy(true); setCancelled(false); setError(null);
    try {
      const signedIn = await registerNative(mode);
      if (mounted.current) { if (signedIn) navigate("/", { replace: true }); else setCancelled(true); }
    } catch (failure) { if (mounted.current) setError(toApiError(failure)); }
    finally { if (mounted.current) setBusy(false); }
  }
  return <section className="card"><h2>{mode === "setup" ? "우리 가계 시작하기" : "배우자 연결"}</h2>
    <p>{mode === "setup" ? "다음 화면에서 이름과 비밀번호를 정하면 바로 시작할 수 있어요." : "다음 화면에 배우자의 8자리 연결 코드와 내 이름·비밀번호를 입력해 주세요."}</p>
    <AuthError error={error} />
    {cancelled && <p role="status">등록을 취소했어요. 준비되면 다시 시작해 주세요.</p>}
    <button type="button" disabled={busy || unavailable} onClick={() => void start()}>{busy ? "등록 화면 사용 중…" : mode === "setup" ? "앱에서 가계 시작하기" : "앱에서 배우자 연결"}</button>
    {error && <button type="button" disabled={busy} onClick={() => void reloadSession()}>로그인 상태 다시 확인</button>}
  </section>;
}

function SetupRegistration() {
  const setup = useSetupAvailability();
  return <>
    {setup.available === null && !setup.error && <p role="status">가계 시작 상태를 확인하고 있어요.</p>}
    <AuthError error={setup.error} />
    {setup.error && <button type="button" onClick={setup.retry}>가계 시작 상태 다시 확인</button>}
    {setup.available === true && (isNativeAuth() ? <NativeRegistration mode="setup" /> : <RegistrationForm mode="setup" />)}
    {setup.available === false && <section className="card"><h2>로그인하거나 배우자와 연결해 주세요</h2><p>지금은 새 가계를 시작할 수 없어요. 이미 만든 계정으로 로그인하거나 배우자에게 연결 코드를 받아 주세요.</p></section>}
    <p><Link className="button-link" to="/onboarding/connect">배우자 연결</Link></p>
    <Link to="/login">로그인하기</Link>
  </>;
}

export function OnboardingPage({ connect = false }: { connect?: boolean }) {
  const { state } = useAuth();
  return <>
    <div className="intro"><p className="eyebrow">함께 시작하기</p><h1>{connect ? "배우자 연결" : "공동 가계 시작"}</h1><p>각자의 계정으로 하나의 가계를 함께 사용해요.</p></div>
    {state.status === "signed-out" ? connect ? isNativeAuth() ? <NativeRegistration mode="connect" /> : <RegistrationForm mode="connect" /> : <SetupRegistration />
      : state.status === "authenticated" ? <section className="card"><h2>이미 로그인되어 있어요</h2><p>배우자에게 줄 연결 코드는 계정과 기기에서 만들 수 있어요.</p><Link className="button-link" to="/settings/auth">계정과 기기 관리</Link></section> : <SessionStatus />}
    {state.status === "signed-out" && <p><Link to="/onboarding/invitation">이전에 받은 초대 코드로 등록</Link></p>}
  </>;
}

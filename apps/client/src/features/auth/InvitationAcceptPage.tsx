import { useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router";
import type { components } from "@sallimbook/api-client";
import { ApiError, toApiError } from "../../platform/api";
import { isNativeAuth } from "../../platform/nativeAuth";
import { NativeAuthAction } from "./NativeAuthAction";
import { AuthError, clearSensitiveFields, SessionStatus, useMounted, useSensitiveForm } from "./AuthFeedback";
import { useAuth } from "./AuthProvider";

function InvitationForm() {
  const { acceptInvitation } = useAuth();
  const formRef = useSensitiveForm();
  const mounted = useMounted();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [validation, setValidation] = useState("");
  const [acceptedName, setAcceptedName] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const form = event.currentTarget;
    const fields = new FormData(form);
    const input: components["schemas"]["InvitationAcceptance"] = {
      token: String(fields.get("token") ?? ""),
      password: String(fields.get("password") ?? ""),
      display_name: String(fields.get("display_name") ?? ""),
    };
    const matches = input.password === fields.get("password_confirmation");
    clearSensitiveFields(form);
    setError(null);
    if (!matches) { setValidation("비밀번호 확인이 일치하지 않아요. 다시 입력해 주세요."); return; }
    setValidation("");
    setBusy(true);
    try {
      const member = await acceptInvitation(input);
      if (mounted.current) setAcceptedName(member.display_name);
    } catch (failure) {
      if (mounted.current) setError(toApiError(failure));
    } finally {
      if (mounted.current) setBusy(false);
    }
  }

  if (acceptedName !== null) return <section className="card" role="status">
    <h2>계정 등록을 마쳤어요</h2><p>{acceptedName} 님, 초대받은 로그인 이름으로 로그인해 주세요. 아직 로그인된 상태는 아니에요.</p>
    <Link className="button-link" to="/login">로그인하기</Link>
  </section>;

  return <section className="card">
    <p>운영자가 발급했거나 함께 쓰는 구성원에게 받은 초대 코드가 필요해요. 로그인 이름은 초대를 만들 때 지정한 이름을 사용해요.</p>
    <form ref={formRef} className="auth-form" onSubmit={(event) => void submit(event)}>
      <div className="form-field"><label htmlFor="invitation-code">초대 코드</label>
        <input id="invitation-code" name="token" type="password" autoComplete="off" required minLength={32} maxLength={128} disabled={busy} />
      </div>
      <div className="form-field"><label htmlFor="invitation-name">표시 이름</label>
        <input id="invitation-name" name="display_name" autoComplete="nickname" required maxLength={80} disabled={busy} />
      </div>
      <div className="form-field"><label htmlFor="invitation-password">새 비밀번호</label>
        <input id="invitation-password" name="password" type="password" autoComplete="new-password" required minLength={15} maxLength={128} disabled={busy} aria-describedby="invitation-password-help" />
        <p id="invitation-password-help" className="muted">15자 이상, 128자 이하로 입력해 주세요.</p>
      </div>
      <div className="form-field"><label htmlFor="invitation-confirmation">새 비밀번호 확인</label>
        <input id="invitation-confirmation" name="password_confirmation" type="password" autoComplete="new-password" required minLength={15} maxLength={128} disabled={busy} />
      </div>
      {validation && <p role="alert">{validation}</p>}
      <AuthError error={error} />
      <button type="submit" disabled={busy}>{busy ? "등록 중…" : "초대 수락하고 계정 등록"}</button>
    </form>
  </section>;
}

export function InvitationAcceptPage() {
  const { state } = useAuth();
  return <>
    <div className="intro"><p className="eyebrow">함께 시작하기</p><h1>공동 가계 시작</h1><p>초대를 받아 두 계정으로 하나의 공동 가계를 사용해요.</p></div>
    {state.status === "signed-out" ? isNativeAuth() ? <NativeAuthAction mode="accept" /> : <InvitationForm /> : state.status === "authenticated"
      ? <section className="card"><h2>현재 계정에서 로그아웃해 주세요</h2><p>이미 로그인되어 있어요. 다른 계정을 등록하려면 먼저 계정 상태를 확인해 주세요.</p><Link className="button-link" to="/settings/auth">계정과 기기 관리</Link></section>
      : <SessionStatus />}
  </>;
}

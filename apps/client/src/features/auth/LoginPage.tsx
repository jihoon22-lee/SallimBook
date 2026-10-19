import { useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router";
import type { components } from "@sallimbook/api-client";
import { ApiError, toApiError } from "../../platform/api";
import { isNativeAuth } from "../../platform/nativeAuth";
import { Icon } from "../../shared/Icon";
import { OnboardingChoices } from "./OnboardingEntry";
import { NativeAuthAction } from "./NativeAuthAction";
import { supportsWebAuthn } from "../../platform/webauthn";
import { useAuthCeremony } from "./useAuthCeremony";
import {
  AuthError,
  clearSensitiveFields,
  SessionStatus,
  useMounted,
  useSensitiveForm,
} from "./AuthFeedback";
import { useAuth } from "./AuthProvider";

function LoginForm() {
  const { state, login, loginPasskey } = useAuth();
  const ceremony = useAuthCeremony();
  const navigate = useNavigate();
  const formRef = useSensitiveForm();
  const mounted = useMounted();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [passwordError, setPasswordError] = useState(true);

  function chooseAccount(loginName: "owner" | "partner") {
    if (busy) return;
    const input = formRef.current?.querySelector<HTMLInputElement>('[name="login_name"]');
    if (input) {
      input.value = loginName;
      clearSensitiveFields(formRef.current);
    }
  }

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
    setPasswordError(true);
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

  async function passkeyLogin() {
    const form = formRef.current;
    if (busy || !form) return;
    const loginName = form.querySelector<HTMLInputElement>('[name="login_name"]');
    const deviceName = form.querySelector<HTMLInputElement>('[name="device_label"]');
    if (!loginName?.reportValidity() || !deviceName?.reportValidity()) return;
    const input = { login_name: loginName.value, device_label: deviceName.value };
    clearSensitiveFields(form);
    setError(null);
    setPasswordError(false);
    setBusy(true);
    try {
      await ceremony.run((signal) => loginPasskey(input, signal));
      if (mounted.current) navigate("/settings/auth", { replace: true });
    } catch (failure) {
      if (mounted.current) setError(toApiError(failure));
    } finally {
      if (mounted.current) setBusy(false);
    }
  }

  return (
    <section className="card login-form-panel">
      {state.status === "authenticated" && (
        <p>
          {state.member.display_name} 님으로 로그인되어 있어요. 현재 계정의 비밀번호를 확인하면 최근
          인증을 갱신해요.
        </p>
      )}
      <form ref={formRef} className="auth-form" onSubmit={(event) => void submit(event)}>
        {state.status !== "authenticated" && (
          <div role="group" aria-label="로그인 계정 선택" className="form-actions">
            <button type="button" disabled={busy} onClick={() => chooseAccount("owner")}>
              처음 시작한 사람
            </button>
            <button type="button" disabled={busy} onClick={() => chooseAccount("partner")}>
              연결한 배우자
            </button>
          </div>
        )}
        {state.status !== "authenticated" && (
          <div className="form-field">
            <label htmlFor="login-name">로그인 이름</label>
            <input
              id="login-name"
              name="login_name"
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
              required
              minLength={3}
              maxLength={64}
              pattern="[a-zA-Z][a-zA-Z0-9_.\-]{2,63}"
              disabled={busy}
            />
          </div>
        )}
        <div className="form-field">
          <label htmlFor="login-password">비밀번호</label>
          <input
            id="login-password"
            name="password"
            type="password"
            autoComplete="current-password"
            required
            maxLength={128}
            disabled={busy}
          />
        </div>
        {state.status !== "authenticated" && (
          <details className="login-device-options">
            <summary>기기 이름 변경</summary>
            <div className="form-field">
              <label htmlFor="login-device">이 기기 이름</label>
              <input
                id="login-device"
                name="device_label"
                autoComplete="off"
                required
                maxLength={80}
                defaultValue="웹 브라우저"
                onInvalid={(event) => {
                  const details = event.currentTarget.closest("details");
                  if (details) details.open = true;
                }}
                disabled={busy}
                aria-describedby="login-device-help"
              />
              <p id="login-device-help" className="muted">
                등록 기기 목록에서 알아볼 수 있는 이름을 적어 주세요.
              </p>
            </div>
          </details>
        )}
        <AuthError error={error} login={passwordError} />
        <button type="submit" disabled={busy}>
          {busy ? "확인 중…" : state.status === "authenticated" ? "다시 인증" : "로그인"}
        </button>
        {state.status !== "authenticated" && (
          <button
            type="button"
            disabled={busy || !supportsWebAuthn()}
            onClick={() => void passkeyLogin()}
          >
            패스키로 로그인
          </button>
        )}
        {busy && !passwordError && (
          <button type="button" onClick={ceremony.cancel}>
            패스키 인증 취소
          </button>
        )}
      </form>
      {state.status !== "authenticated" && (
        <p className="muted">
          패스키 로그인에는 로그인 이름과 이 기기 이름만 필요해요. 비밀번호를 입력하지 않아도 돼요.
        </p>
      )}
      {state.status !== "authenticated" && !supportsWebAuthn() && (
        <p>
          이 브라우저에서는 패스키를 사용할 수 없어요. 최신 브라우저의 HTTPS 주소에서 이용해 주세요.
        </p>
      )}
      {state.status !== "authenticated" && (
        <p className="muted">
          계정을 선택하면 로그인 이름을 채워 드려요. 기존에 쓰던 이름도 직접 입력할 수 있어요.
        </p>
      )}
    </section>
  );
}

export function LoginPage() {
  const { state } = useAuth();
  return (
    <div className="auth-layout">
      <aside className="auth-story" aria-label="살림북 소개">
        <span className="auth-story-mark">
          <Icon name="book" size={42} />
        </span>
        <p className="eyebrow">SALLIMBOOK · 살림북</p>
        <h2>
          우리 집의 기록을,
          <br />
          함께 쌓아가요.
        </h2>
        <p>
          자산부터 일상의 작은 물건까지.
          <br />두 사람의 살림을 한곳에서 살펴보세요.
        </p>
        <ul>
          <li>
            <Icon name="assets" />
            함께 확인하는 월간 자산
          </li>
          <li>
            <Icon name="insurance" />
            차근차근 정리하는 보험 기록
          </li>
          <li>
            <Icon name="package" />
            오늘 챙길 가전과 소모품
          </li>
        </ul>
        <p className="auth-story-foot">각자의 계정 · 하나의 공동 가계</p>
      </aside>
      <div className="auth-content">
        <div className="intro">
          <p className="eyebrow">다시 만나 반가워요</p>
          <h1>로그인</h1>
          <p>각자의 계정으로 하나의 공동 가계를 사용해요.</p>
        </div>
        {state.status === "signed-out" && state.remoteRevocationUnconfirmed && (
          <p role="status">
            이 기기에서는 로그아웃했어요. 서버 연결을 확인하지 못해 다른 기기에서 이 기기의 연결
            해제를 확인해 주세요.
          </p>
        )}
        {state.status === "signed-out" || state.status === "authenticated" ? (
          isNativeAuth() ? (
            <NativeAuthAction mode="login" />
          ) : (
            <LoginForm />
          )
        ) : (
          <SessionStatus />
        )}
        {state.status === "signed-out" && <OnboardingChoices compact />}
      </div>
    </div>
  );
}

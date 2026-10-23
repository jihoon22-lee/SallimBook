import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router";
import type { components } from "@sallimbook/api-client";
import { ApiError, toApiError } from "../../platform/api";
import { isNativeAuth } from "../../platform/nativeAuth";
import { NativeAuthAction } from "./NativeAuthAction";
import { ConnectionCodePanel } from "./ConnectionCodePanel";
import { PasskeyPanel } from "./PasskeyPanel";
import { useAuthCeremony } from "./useAuthCeremony";
import { supportsWebAuthn } from "../../platform/webauthn";
import {
  AuthError,
  clearSensitiveFields,
  SessionStatus,
  useMounted,
  useSensitiveForm,
} from "./AuthFeedback";
import { useAuth } from "./AuthProvider";
import type { Device, Member, PasswordChange } from "./AuthProvider";
import { FormError } from "../../shared/formValidation";
import { ReturnLoginLink } from "./ReturnLoginLink";
import { formatSeoulDateTime } from "../../shared/format";

function InvitationPanel() {
  const { createPartnerInvitation } = useAuth();
  const ceremony = useAuthCeremony();
  const mounted = useMounted();
  const generation = useRef(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [invitation, setInvitation] = useState<components["schemas"]["InvitationResponse"] | null>(
    null,
  );
  const [revealed, setRevealed] = useState(false);

  useEffect(() => {
    const clear = () => {
      generation.current += 1;
      setInvitation(null);
      setRevealed(false);
    };
    const onVisibility = () => {
      if (document.visibilityState !== "visible") clear();
    };
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("pagehide", clear);
    return () => {
      generation.current += 1;
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("pagehide", clear);
    };
  }, []);

  useEffect(() => {
    if (!invitation) return;
    const remaining = Date.parse(invitation.expires_at) - Date.now();
    const timeout = window.setTimeout(
      () => {
        setInvitation(null);
        setRevealed(false);
      },
      Number.isFinite(remaining) ? Math.max(0, Math.min(remaining, 900_000)) : 0,
    );
    return () => window.clearTimeout(timeout);
  }, [invitation]);

  useEffect(() => {
    if (!invitation || !revealed) return;
    // The bearer invitation's lifetime and its visible lifetime are separate limits.
    const remaining = Date.parse(invitation.expires_at) - Date.now();
    const timeout = window.setTimeout(
      () => {
        setInvitation(null);
        setRevealed(false);
      },
      Number.isFinite(remaining) ? Math.max(0, Math.min(remaining, 30_000)) : 0,
    );
    return () => window.clearTimeout(timeout);
  }, [invitation, revealed]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const input: components["schemas"]["InvitationRequest"] = {
      intended_login: String(new FormData(event.currentTarget).get("intended_login") ?? ""),
    };
    const requestGeneration = ++generation.current;
    setBusy(true);
    setError(null);
    setInvitation(null);
    setRevealed(false);
    try {
      const stepUp =
        (event.nativeEvent as SubmitEvent).submitter?.getAttribute("name") === "step_up";
      const response = await ceremony.run((signal) =>
        createPartnerInvitation(input, { signal, stepUp }),
      );
      if (
        mounted.current &&
        generation.current === requestGeneration &&
        document.visibilityState === "visible"
      )
        setInvitation(response);
    } catch (failure) {
      if (mounted.current && generation.current === requestGeneration)
        setError(toApiError(failure));
    } finally {
      if (mounted.current) setBusy(false);
    }
  }

  return (
    <section className="card" aria-labelledby="partner-invitation-title">
      <h2 id="partner-invitation-title">함께 쓸 구성원 초대</h2>
      <p>
        두 번째 계정의 로그인 이름을 정해 초대해요. 새 초대를 만들면 이전에 사용하지 않은 초대
        코드는 무효가 돼요.
      </p>
      <form className="auth-form" onSubmit={(event) => void submit(event)}>
        <div className="form-field">
          <label htmlFor="partner-login-name">초대할 로그인 이름</label>
          <input
            id="partner-login-name"
            name="intended_login"
            autoComplete="off"
            autoCapitalize="none"
            spellCheck={false}
            required
            minLength={3}
            maxLength={64}
            pattern="[a-zA-Z][a-zA-Z0-9_.\-]{2,63}"
            disabled={busy}
          />
        </div>
        <AuthError error={error} />
        <button type="submit" disabled={busy}>
          {busy ? "초대 생성 중…" : "초대 만들기"}
        </button>
        {supportsWebAuthn() && (
          <button type="submit" name="step_up" disabled={busy}>
            패스키로 확인하고 초대
          </button>
        )}
        {busy && (
          <button type="button" onClick={ceremony.cancel}>
            인증 요청 취소
          </button>
        )}
      </form>
      {invitation && (
        <div className="invitation-result">
          <p role="status">
            초대를 만들었어요. 만료:{" "}
            {formatSeoulDateTime(invitation.expires_at, { fallback: "확인되지 않음" })} (서울 기준)
          </p>
          <p>
            초대받는 사람에게 코드를 전달하고 공동 가계 시작 화면에 직접 입력하도록 안내해 주세요.
            이 화면을 벗어나면 코드는 보관하지 않아요.
          </p>
          {revealed ? (
            <>
              <output aria-label="생성된 초대 코드">{invitation.token}</output>
              <button
                type="button"
                onClick={() => {
                  setInvitation(null);
                  setRevealed(false);
                }}
              >
                초대 코드 가리기
              </button>
            </>
          ) : (
            <button type="button" onClick={() => setRevealed(true)}>
              초대 코드 보기
            </button>
          )}
          <Link to="/onboarding/invitation">기존 초대 수락 화면</Link>
        </div>
      )}
    </section>
  );
}

const possiblyApplied =
  "응답을 받지 못했어요. 비밀번호가 이미 바뀌었을 수 있으니, 다시 시도할 때는 현재 비밀번호 칸에 새 비밀번호를 넣어 보세요.";

function PasswordPanel({ onChanged }: { onChanged: () => void }) {
  const { changePassword } = useAuth();
  const formRef = useSensitiveForm();
  const mounted = useMounted();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  async function run(input?: PasswordChange) {
    setBusy(true);
    try {
      if ((await changePassword(input)) && mounted.current) {
        setDone(true);
        onChanged();
      }
    } catch (failure) {
      if (mounted.current) setError(toApiError(failure));
    } finally {
      if (mounted.current) setBusy(false);
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    if (busy) return;
    const fields = new FormData(form);
    const input: PasswordChange = {
      current_password: String(fields.get("current_password") ?? ""),
      new_password: String(fields.get("new_password") ?? ""),
    };
    const confirmation = String(fields.get("new_password_confirmation") ?? "");
    clearSensitiveFields(form);
    setError(null);
    setDone(false);
    const invalid =
      input.new_password !== confirmation
        ? "새 비밀번호와 확인 입력이 달라요."
        : input.new_password === input.current_password
          ? "현재 비밀번호와 다른 새 비밀번호를 입력해 주세요."
          : null;
    setProblem(invalid);
    if (!invalid) void run(input);
  }

  return (
    <section className="card" aria-labelledby="password-change-title">
      <h2 id="password-change-title">비밀번호 변경</h2>
      <p>바꾸면 이 기기를 뺀 내 다른 기기는 모두 로그아웃돼요. 등록한 패스키는 그대로 유지돼요.</p>
      {isNativeAuth() ? (
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            setError(null);
            setDone(false);
            void run();
          }}
        >
          {busy ? "인증 화면 사용 중…" : "앱에서 비밀번호 변경"}
        </button>
      ) : (
        <form ref={formRef} className="auth-form" onSubmit={submit}>
          <div className="form-field">
            <label htmlFor="current-password">현재 비밀번호</label>
            <input
              id="current-password"
              name="current_password"
              type="password"
              autoComplete="current-password"
              required
              maxLength={128}
              disabled={busy}
            />
          </div>
          <div className="form-field">
            <label htmlFor="new-password">새 비밀번호</label>
            <input
              id="new-password"
              name="new_password"
              type="password"
              autoComplete="new-password"
              required
              minLength={15}
              maxLength={128}
              disabled={busy}
              aria-describedby="new-password-help"
            />
            <p id="new-password-help" className="muted">
              15자 이상으로 정해 주세요.
            </p>
          </div>
          <div className="form-field">
            <label htmlFor="new-password-confirmation">새 비밀번호 확인</label>
            <input
              id="new-password-confirmation"
              name="new_password_confirmation"
              type="password"
              autoComplete="new-password"
              required
              minLength={15}
              maxLength={128}
              disabled={busy}
            />
          </div>
          {problem && <FormError message={problem} />}
          <button type="submit" disabled={busy}>
            {busy ? "변경 중…" : "비밀번호 변경"}
          </button>
        </form>
      )}
      <AuthError error={error} />
      {error?.code === "NETWORK_UNAVAILABLE" && <p className="muted">{possiblyApplied}</p>}
      {done && <p role="status">비밀번호를 바꿨어요. 다른 기기는 모두 로그아웃됐어요.</p>}
    </section>
  );
}

function DevicePanel() {
  const { listDevices, revokeDevice, revokeOtherDevices } = useAuth();
  const ceremony = useAuthCeremony();
  const mounted = useMounted();
  const generation = useRef(0);
  const [devices, setDevices] = useState<Device[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [actionError, setActionError] = useState<ApiError | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const confirmButton = useRef<HTMLButtonElement>(null);
  const [revoking, setRevoking] = useState(false);
  const [signOutOpen, setSignOutOpen] = useState(false);
  const [signedOut, setSignedOut] = useState(false);
  const signOutForm = useSensitiveForm();
  useEffect(() => {
    // The 연결 해제 button that opened the confirmation unmounts, so focus moves to its replacement.
    if (confirming) confirmButton.current?.focus();
  }, [confirming]);

  const load = useCallback(
    async (cursor?: string) => {
      const requestGeneration = ++generation.current;
      setLoading(true);
      setError(null);
      setConfirming(null);
      try {
        const response = await listDevices(cursor);
        if (!mounted.current || generation.current !== requestGeneration) return;
        setDevices((previous) =>
          cursor
            ? [
                ...previous,
                ...response.items.filter((item) => !previous.some((known) => known.id === item.id)),
              ]
            : response.items,
        );
        setNextCursor(response.next_cursor);
      } catch (failure) {
        if (mounted.current && generation.current === requestGeneration)
          setError(toApiError(failure));
      } finally {
        if (mounted.current && generation.current === requestGeneration) setLoading(false);
      }
    },
    [listDevices, mounted],
  );

  useEffect(() => {
    void load();
    return () => {
      generation.current += 1;
    };
  }, [load]);

  async function revoke(device: Device, stepUp = false) {
    if (revoking || loading) return;
    setRevoking(true);
    setActionError(null);
    try {
      const revoked = await ceremony.run((signal) => revokeDevice(device, { signal, stepUp }));
      if (revoked && mounted.current && !device.current) await load();
    } catch (failure) {
      if (mounted.current) setActionError(toApiError(failure));
    } finally {
      if (mounted.current) {
        setRevoking(false);
        setConfirming(null);
      }
    }
  }

  async function signOutOthers(password?: string) {
    if (revoking || loading) return;
    setRevoking(true);
    setActionError(null);
    setSignedOut(false);
    try {
      if ((await revokeOtherDevices(password)) && mounted.current) {
        setSignOutOpen(false);
        setSignedOut(true);
        await load();
      }
    } catch (failure) {
      if (mounted.current) setActionError(toApiError(failure));
    } finally {
      if (mounted.current) setRevoking(false);
    }
  }

  function submitSignOut(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const password = String(new FormData(form).get("password") ?? "");
    clearSensitiveFields(form);
    void signOutOthers(password);
  }
  const card = (device: Device) => (
    <li className="device-card" key={device.id}>
      <h3>
        {device.label} {device.current && <span className="status-chip">현재 기기</span>}
      </h3>
      <p>
        {device.platform === "android" ? "Android 앱" : "웹 브라우저"} ·{" "}
        {device.status !== "active"
          ? "연결 해제됨"
          : device.login_state === "expired"
            ? "만료"
            : "연결됨"}
      </p>
      <p className="muted">
        최근 사용: {formatSeoulDateTime(device.last_seen_at, { fallback: "확인되지 않음" })} (서울
        기준)
      </p>
      {device.status === "active" &&
        (confirming === device.id ? (
          <div role="group" aria-label={`${device.label} 연결 해제 확인`}>
            <p>
              {device.current
                ? "이 기기에서 로그아웃하고 연결을 해제할까요?"
                : "이 기기의 로그인 연결을 해제할까요?"}
            </p>
            <div className="form-actions">
              <button
                type="button"
                ref={confirmButton}
                disabled={revoking || loading || Boolean(error)}
                onClick={() => void revoke(device)}
              >
                {revoking ? "연결 해제 중…" : "연결 해제 확인"}
              </button>
              {(supportsWebAuthn() || isNativeAuth()) && (
                <button
                  type="button"
                  disabled={revoking || loading || Boolean(error)}
                  onClick={() => void revoke(device, true)}
                >
                  패스키로 확인하고 연결 해제
                </button>
              )}
              <button
                type="button"
                onClick={() => {
                  ceremony.cancel();
                  if (!revoking) setConfirming(null);
                }}
              >
                취소
              </button>
            </div>
          </div>
        ) : (
          <button
            type="button"
            disabled={revoking || loading || Boolean(error)}
            aria-label={`${device.label} 연결 해제`}
            onClick={() => {
              setActionError(null);
              setConfirming(device.id);
            }}
          >
            연결 해제
          </button>
        ))}
    </li>
  );
  // A device whose sign-in ran out is folded away so a new, unknown device stands out.
  const expired = devices.filter(
    (device) => device.status === "active" && device.login_state === "expired",
  );
  const listed = devices.filter((device) => !expired.includes(device));
  return (
    <section className="card" aria-labelledby="device-list-title">
      <h2 id="device-list-title">내 등록 기기</h2>
      <p>
        내 계정으로 등록된 기기를 확인하고 연결을 해제할 수 있어요. 현재 기기를 해제하면
        로그아웃돼요.
      </p>
      <button
        type="button"
        disabled={loading || revoking}
        onClick={() => {
          setActionError(null);
          void load();
        }}
      >
        기기 목록 다시 불러오기
      </button>
      {loading && (
        <p className="loading-state" role="status">
          기기 목록을 불러오고 있어요.
        </p>
      )}
      <AuthError error={error} />
      <AuthError error={actionError} />
      {error && devices.length > 0 && (
        <p className="muted">
          표시된 목록은 최신 상태가 아닐 수 있어요. 다시 불러오기 전에는 연결을 해제할 수 없어요.
        </p>
      )}
      {!loading && !error && devices.length === 0 && <p>등록된 기기가 없어요.</p>}
      <ul className="device-list">{listed.map(card)}</ul>
      {expired.length > 0 && (
        <details className="secondary-actions">
          <summary>만료된 기기 {expired.length}개</summary>
          <p className="muted">
            로그인이 만료된 기기예요. 다시 로그인하면 연결됨으로 바뀌고, 90일 동안 쓰지 않으면
            목록에서 빠져요.
          </p>
          <ul className="device-list">{expired.map(card)}</ul>
        </details>
      )}
      {nextCursor && (
        <button type="button" disabled={loading || revoking} onClick={() => void load(nextCursor)}>
          기기 더 보기
        </button>
      )}
      {isNativeAuth() ? (
        <button type="button" disabled={loading || revoking} onClick={() => void signOutOthers()}>
          다른 기기 모두 로그아웃
        </button>
      ) : signOutOpen ? (
        <form
          ref={signOutForm}
          className="auth-form"
          aria-label="다른 기기 모두 로그아웃 확인"
          onSubmit={submitSignOut}
        >
          <p>
            현재 계정의 비밀번호를 확인하면 이 기기를 뺀 내 기기의 로그인을 모두 해제해요. 등록한
            패스키는 그대로 유지돼요.
          </p>
          <div className="form-field">
            <label htmlFor="sign-out-others-password">현재 계정 비밀번호</label>
            <input
              id="sign-out-others-password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              maxLength={128}
              disabled={revoking}
            />
          </div>
          <div className="form-actions">
            <button type="submit" disabled={revoking || loading}>
              {revoking ? "로그아웃 중…" : "다른 기기 로그아웃 확인"}
            </button>
            <button
              type="button"
              onClick={() => {
                clearSensitiveFields(signOutForm.current);
                setSignOutOpen(false);
              }}
            >
              취소
            </button>
          </div>
        </form>
      ) : (
        <button
          type="button"
          disabled={loading || revoking}
          onClick={() => {
            setActionError(null);
            setSignedOut(false);
            setSignOutOpen(true);
          }}
        >
          다른 기기 모두 로그아웃
        </button>
      )}
      {signedOut && <p role="status">다른 기기를 모두 로그아웃했어요.</p>}
    </section>
  );
}

function AuthenticatedSettings({ member }: { member: Member }) {
  const { logout } = useAuth();
  const mounted = useMounted();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [secretReset, setSecretReset] = useState(0);
  const [legacyOpen, setLegacyOpen] = useState(false);
  const [deviceReload, setDeviceReload] = useState(0);
  async function signOut() {
    if (busy) return;
    setSecretReset((value) => value + 1);
    setBusy(true);
    setError(null);
    try {
      await logout();
    } catch (failure) {
      if (mounted.current) setError(toApiError(failure));
    } finally {
      if (mounted.current) setBusy(false);
    }
  }
  return (
    <div className="session-details">
      <section className="card" aria-labelledby="current-member-title">
        <h2 id="current-member-title">현재 계정</h2>
        <p>
          <strong>{member.display_name}</strong> 님으로 로그인되어 있어요.
        </p>
        <p>
          {member.role === "owner" ? "가계 관리자" : "가계 구성원"} · 부부 두 계정이 하나의 가계를
          함께 사용해요.
        </p>
        <AuthError error={error} />
        <div className="form-actions">
          <button type="button" disabled={busy} onClick={() => void signOut()}>
            {busy ? "로그아웃 중…" : "로그아웃"}
          </button>
          <ReturnLoginLink className="button-link">최근 로그인 다시 확인</ReturnLoginLink>
        </div>
      </section>
      <PasswordPanel onChanged={() => setDeviceReload((value) => value + 1)} />
      {member.role === "owner" && (
        <ConnectionCodePanel
          key={`connection:${secretReset}`}
          onLegacyInvitation={() => setLegacyOpen(true)}
        />
      )}
      <DevicePanel key={`devices:${deviceReload}`} />
      <PasskeyPanel />
      {member.role === "owner" ? (
        <details open={legacyOpen} onToggle={(event) => setLegacyOpen(event.currentTarget.open)}>
          <summary>기존 로그인 이름으로 초대</summary>
          {legacyOpen &&
            (isNativeAuth() ? (
              <NativeAuthAction mode="invite" />
            ) : (
              <InvitationPanel key={secretReset} />
            ))}
        </details>
      ) : (
        <section className="card">
          <h2>구성원 초대</h2>
          <p>두 번째 구성원 초대는 가계 관리자 계정에서 만들 수 있어요.</p>
        </section>
      )}
    </div>
  );
}

export function SessionSettings() {
  const { state } = useAuth();
  return (
    <>
      <div className="intro">
        <p className="eyebrow">함께 쓰는 계정</p>
        <h1>계정과 기기</h1>
        <p>로그인한 계정, 내 등록 기기와 구성원 초대를 관리해요.</p>
      </div>
      {state.status === "authenticated" ? (
        <AuthenticatedSettings key={state.member.member_id} member={state.member} />
      ) : (
        <SessionStatus />
      )}
    </>
  );
}

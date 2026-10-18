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
import { AuthError, SessionStatus, useMounted } from "./AuthFeedback";
import { useAuth } from "./AuthProvider";
import type { Device, Member } from "./AuthProvider";

function localDate(value: string) {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "확인되지 않음";
  return new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", dateStyle: "medium", timeStyle: "short" }).format(date);
}

function InvitationPanel() {
  const { createPartnerInvitation } = useAuth();
  const ceremony = useAuthCeremony();
  const mounted = useMounted();
  const generation = useRef(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [invitation, setInvitation] = useState<components["schemas"]["InvitationResponse"] | null>(null);
  const [revealed, setRevealed] = useState(false);

  useEffect(() => {
    const clear = () => { generation.current += 1; setInvitation(null); setRevealed(false); };
    const onVisibility = () => { if (document.visibilityState !== "visible") clear(); };
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
    const timeout = window.setTimeout(() => { setInvitation(null); setRevealed(false); }, Number.isFinite(remaining) ? Math.max(0, Math.min(remaining, 900_000)) : 0);
    return () => window.clearTimeout(timeout);
  }, [invitation]);

  useEffect(() => {
    if (!invitation || !revealed) return;
    // The bearer invitation's lifetime and its visible lifetime are separate limits.
    const remaining = Date.parse(invitation.expires_at) - Date.now();
    const timeout = window.setTimeout(() => { setInvitation(null); setRevealed(false); },
      Number.isFinite(remaining) ? Math.max(0, Math.min(remaining, 30_000)) : 0);
    return () => window.clearTimeout(timeout);
  }, [invitation, revealed]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const input: components["schemas"]["InvitationRequest"] = { intended_login: String(new FormData(event.currentTarget).get("intended_login") ?? "") };
    const requestGeneration = ++generation.current;
    setBusy(true);
    setError(null);
    setInvitation(null);
    setRevealed(false);
    try {
      const stepUp = (event.nativeEvent as SubmitEvent).submitter?.getAttribute("name") === "step_up";
      const response = await ceremony.run((signal) => createPartnerInvitation(input, { signal, stepUp }));
      if (mounted.current && generation.current === requestGeneration && document.visibilityState === "visible") setInvitation(response);
    } catch (failure) {
      if (mounted.current && generation.current === requestGeneration) setError(toApiError(failure));
    } finally {
      if (mounted.current) setBusy(false);
    }
  }

  return <section className="card" aria-labelledby="partner-invitation-title">
    <h2 id="partner-invitation-title">함께 쓸 구성원 초대</h2>
    <p>두 번째 계정의 로그인 이름을 정해 초대해요. 새 초대를 만들면 이전에 사용하지 않은 초대 코드는 무효가 돼요.</p>
    <form className="auth-form" onSubmit={(event) => void submit(event)}>
      <div className="form-field"><label htmlFor="partner-login-name">초대할 로그인 이름</label>
        <input id="partner-login-name" name="intended_login" autoComplete="off" autoCapitalize="none" spellCheck={false} required minLength={3} maxLength={64} pattern="[a-zA-Z][a-zA-Z0-9_.\-]{2,63}" disabled={busy} />
      </div>
      <AuthError error={error} />
      <button type="submit" disabled={busy}>{busy ? "초대 생성 중…" : "초대 만들기"}</button>
      {supportsWebAuthn() && <button type="submit" name="step_up" disabled={busy}>패스키로 확인하고 초대</button>}
      {busy && <button type="button" onClick={ceremony.cancel}>인증 요청 취소</button>}
    </form>
    {invitation && <div className="invitation-result">
      <p role="status">초대를 만들었어요. 만료: {localDate(invitation.expires_at)} (서울 기준)</p>
      <p>초대받는 사람에게 코드를 전달하고 공동 가계 시작 화면에 직접 입력하도록 안내해 주세요. 이 화면을 벗어나면 코드는 보관하지 않아요.</p>
      {revealed ? <><output aria-label="생성된 초대 코드">{invitation.token}</output><button type="button" onClick={() => { setInvitation(null); setRevealed(false); }}>초대 코드 가리기</button></>
        : <button type="button" onClick={() => setRevealed(true)}>초대 코드 보기</button>}
      <Link to="/onboarding/invitation">기존 초대 수락 화면</Link>
    </div>}
  </section>;
}

function DevicePanel() {
  const { listDevices, revokeDevice } = useAuth();
  const ceremony = useAuthCeremony();
  const mounted = useMounted();
  const generation = useRef(0);
  const [devices, setDevices] = useState<Device[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [actionError, setActionError] = useState<ApiError | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [revoking, setRevoking] = useState(false);

  const load = useCallback(async (cursor?: string) => {
    const requestGeneration = ++generation.current;
    setLoading(true);
    setError(null);
    setConfirming(null);
    try {
      const response = await listDevices(cursor);
      if (!mounted.current || generation.current !== requestGeneration) return;
      setDevices((previous) => cursor ? [...previous, ...response.items.filter((item) => !previous.some((known) => known.id === item.id))] : response.items);
      setNextCursor(response.next_cursor);
    } catch (failure) {
      if (mounted.current && generation.current === requestGeneration) setError(toApiError(failure));
    } finally {
      if (mounted.current && generation.current === requestGeneration) setLoading(false);
    }
  }, [listDevices, mounted]);

  useEffect(() => { void load(); return () => { generation.current += 1; }; }, [load]);

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
      if (mounted.current) { setRevoking(false); setConfirming(null); }
    }
  }

  return <section className="card" aria-labelledby="device-list-title">
    <h2 id="device-list-title">내 등록 기기</h2>
    <p>내 계정으로 등록된 기기를 확인하고 연결을 해제할 수 있어요. 현재 기기를 해제하면 로그아웃돼요.</p>
    <button type="button" disabled={loading || revoking} onClick={() => { setActionError(null); void load(); }}>기기 목록 다시 불러오기</button>
    {loading && <p className="loading-state" role="status">기기 목록을 불러오고 있어요.</p>}
    <AuthError error={error} />
    <AuthError error={actionError} />
    {error && devices.length > 0 && <p className="muted">표시된 목록은 최신 상태가 아닐 수 있어요. 다시 불러오기 전에는 연결을 해제할 수 없어요.</p>}
    {!loading && !error && devices.length === 0 && <p>등록된 기기가 없어요.</p>}
    <ul className="device-list">{devices.map((device) => <li className="device-card" key={device.id}>
      <h3>{device.label} {device.current && <span className="status-chip">현재 기기</span>}</h3>
      <p>{device.platform === "android" ? "Android 앱" : "웹 브라우저"} · {device.status === "active" ? "연결됨" : "연결 해제됨"}</p>
      <p className="muted">최근 사용: {localDate(device.last_seen_at)} (서울 기준)</p>
      {device.status === "active" && (confirming === device.id
        ? <div role="group" aria-label={`${device.label} 연결 해제 확인`}>
            <p>{device.current ? "이 기기에서 로그아웃하고 연결을 해제할까요?" : "이 기기의 로그인 연결을 해제할까요?"}</p>
            <div className="form-actions"><button type="button" autoFocus disabled={revoking || loading || Boolean(error)} onClick={() => void revoke(device)}>{revoking ? "연결 해제 중…" : "연결 해제 확인"}</button>
              {(supportsWebAuthn() || isNativeAuth()) && <button type="button" disabled={revoking || loading || Boolean(error)} onClick={() => void revoke(device, true)}>패스키로 확인하고 연결 해제</button>}
              <button type="button" onClick={() => { ceremony.cancel(); if (!revoking) setConfirming(null); }}>취소</button></div>
          </div>
        : <button type="button" disabled={revoking || loading || Boolean(error)} aria-label={`${device.label} 연결 해제`} onClick={() => { setActionError(null); setConfirming(device.id); }}>연결 해제</button>)}
    </li>)}</ul>
    {nextCursor && <button type="button" disabled={loading || revoking} onClick={() => void load(nextCursor)}>기기 더 보기</button>}
  </section>;
}

function AuthenticatedSettings({ member }: { member: Member }) {
  const { logout } = useAuth();
  const mounted = useMounted();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [secretReset, setSecretReset] = useState(0);
  const [legacyOpen, setLegacyOpen] = useState(false);
  async function signOut() {
    if (busy) return;
    setSecretReset((value) => value + 1);
    setBusy(true);
    setError(null);
    try { await logout(); }
    catch (failure) { if (mounted.current) setError(toApiError(failure)); }
    finally { if (mounted.current) setBusy(false); }
  }
  return <div className="session-details">
    <section className="card" aria-labelledby="current-member-title">
      <h2 id="current-member-title">현재 계정</h2>
      <p><strong>{member.display_name}</strong> 님으로 로그인되어 있어요.</p>
      <p>{member.role === "owner" ? "가계 관리자" : "가계 구성원"} · 부부 두 계정이 하나의 가계를 함께 사용해요.</p>
      <AuthError error={error} />
      <div className="form-actions"><button type="button" disabled={busy} onClick={() => void signOut()}>{busy ? "로그아웃 중…" : "로그아웃"}</button><Link className="button-link" to="/login">최근 로그인 다시 확인</Link></div>
    </section>
    {member.role === "owner" && <ConnectionCodePanel key={`connection:${secretReset}`} onLegacyInvitation={() => setLegacyOpen(true)} />}
    <DevicePanel />
    <PasskeyPanel />
    {member.role === "owner" ? <details open={legacyOpen} onToggle={(event) => setLegacyOpen(event.currentTarget.open)}><summary>기존 로그인 이름으로 초대</summary>{legacyOpen && (isNativeAuth() ? <NativeAuthAction mode="invite" /> : <InvitationPanel key={secretReset} />)}</details> : <section className="card"><h2>구성원 초대</h2><p>두 번째 구성원 초대는 가계 관리자 계정에서 만들 수 있어요.</p></section>}
  </div>;
}

export function SessionSettings() {
  const { state } = useAuth();
  return <>
    <div className="intro"><p className="eyebrow">함께 쓰는 계정</p><h1>계정과 기기</h1><p>로그인한 계정, 내 등록 기기와 구성원 초대를 관리해요.</p></div>
    {state.status === "authenticated" ? <AuthenticatedSettings key={state.member.member_id} member={state.member} /> : <SessionStatus />}
  </>;
}

import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router";
import { ApiError, toApiError } from "../../platform/api";
import { isNativeAuth } from "../../platform/nativeAuth";
import { supportsWebAuthn } from "../../platform/webauthn";
import { AuthError, useMounted } from "./AuthFeedback";
import { useAuth } from "./AuthProvider";
import type { Passkey } from "./AuthProvider";
import { useAuthCeremony } from "./useAuthCeremony";

function dateLabel(value: string | null): string {
  if (!value) return "사용 기록 없음";
  const date = new Date(value);
  return Number.isFinite(date.getTime())
    ? new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", dateStyle: "medium" }).format(date)
    : "확인되지 않음";
}

export function PasskeyPanel() {
  const { listPasskeys, registerPasskey, revokePasskey } = useAuth();
  const mounted = useMounted();
  const ceremony = useAuthCeremony();
  const generation = useRef(0);
  const [items, setItems] = useState<Passkey[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [authenticating, setAuthenticating] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [actionError, setActionError] = useState<ApiError | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const native = isNativeAuth();
  const supported = !native && supportsWebAuthn();

  const load = useCallback(
    async (after?: string) => {
      const requestGeneration = ++generation.current;
      setLoading(true);
      setError(null);
      setConfirming(null);
      try {
        const response = await listPasskeys(after);
        if (!mounted.current || generation.current !== requestGeneration) return;
        setItems((previous) =>
          after
            ? [
                ...previous,
                ...response.items.filter((item) => !previous.some((known) => known.id === item.id)),
              ]
            : response.items,
        );
        setCursor(response.next_cursor);
      } catch (failure) {
        if (mounted.current && generation.current === requestGeneration)
          setError(toApiError(failure));
      } finally {
        if (mounted.current && generation.current === requestGeneration) setLoading(false);
      }
    },
    [listPasskeys, mounted],
  );

  useEffect(() => {
    void load();
    return () => {
      generation.current++;
    };
  }, [load]);

  async function register(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const form = event.currentTarget;
    const label = String(new FormData(form).get("passkey_label") ?? "");
    setBusy(true);
    setAuthenticating(true);
    setActionError(null);
    setDone(false);
    try {
      await ceremony.run((signal) => registerPasskey(label, signal));
      if (mounted.current) {
        form.reset();
        setDone(true);
        await load();
      }
    } catch (failure) {
      if (mounted.current) setActionError(toApiError(failure));
    } finally {
      if (mounted.current) {
        setBusy(false);
        setAuthenticating(false);
      }
    }
  }

  async function registerNative() {
    if (busy) return;
    setBusy(true);
    setActionError(null);
    setDone(false);
    try {
      const registered = await ceremony.run((signal) => registerPasskey("", signal));
      if (registered && mounted.current) {
        setDone(true);
        await load();
      }
    } catch (failure) {
      if (mounted.current) setActionError(toApiError(failure));
    } finally {
      if (mounted.current) setBusy(false);
    }
  }

  async function revoke(item: Passkey) {
    if (busy || loading) return;
    setBusy(true);
    setActionError(null);
    setDone(false);
    try {
      if ((await revokePasskey(item)) && mounted.current) await load();
    } catch (failure) {
      if (mounted.current) setActionError(toApiError(failure));
    } finally {
      if (mounted.current) {
        setBusy(false);
        setConfirming(null);
      }
    }
  }

  return (
    <section className="card" aria-labelledby="passkey-list-title">
      <h2 id="passkey-list-title">내 패스키</h2>
      <p>
        패스키로 이 계정에 로그인하고 중요한 작업을 확인할 수 있어요. 패스키 등록과 해제에는 5분
        이내의 계정 로그인이 필요해요.
      </p>
      <Link className="button-link" to="/login">
        패스키 관리 전 다시 로그인
      </Link>
      {!native &&
        (supported ? (
          <form className="auth-form" onSubmit={(event) => void register(event)}>
            <div className="form-field">
              <label htmlFor="passkey-label">패스키 이름</label>
              <input
                id="passkey-label"
                name="passkey_label"
                maxLength={80}
                minLength={1}
                required
                autoComplete="off"
                disabled={busy}
                placeholder="내 노트북 패스키"
              />
            </div>
            <button type="submit" disabled={busy}>
              {busy ? "패스키 확인 중…" : "패스키 등록"}
            </button>
          </form>
        ) : (
          <p>
            이 브라우저에서는 패스키를 사용할 수 없어요. 최신 브라우저의 HTTPS 주소에서 다시 시도해
            주세요.
          </p>
        ))}
      {native && (
        <button type="button" disabled={busy} onClick={() => void registerNative()}>
          앱에서 패스키 등록
        </button>
      )}
      <AuthError error={actionError} />
      {done && <p role="status">패스키를 등록했어요.</p>}
      {authenticating && !native && (
        <button type="button" onClick={ceremony.cancel}>
          패스키 인증 취소
        </button>
      )}
      <button
        type="button"
        disabled={loading || busy}
        onClick={() => {
          setActionError(null);
          void load();
        }}
      >
        패스키 목록 다시 불러오기
      </button>
      {loading && (
        <p className="loading-state" role="status">
          패스키 목록을 불러오고 있어요.
        </p>
      )}
      <AuthError error={error} />
      {error && items.length > 0 && (
        <p>표시된 패스키 목록은 최신 상태가 아닐 수 있어요. 다시 불러온 뒤 해제해 주세요.</p>
      )}
      {!loading && !error && items.length === 0 && <p>등록된 패스키가 없어요.</p>}
      <ul className="device-list">
        {items.map((item) => (
          <li className="device-card" key={item.id}>
            <h3>{item.label}</h3>
            <p>
              {item.device_type === "multi_device"
                ? "여러 기기에서 사용할 수 있는 패스키"
                : "단일 기기 패스키"}{" "}
              · {item.backed_up ? "인증기가 백업됨을 보고함" : "백업 확인 안 됨"}
            </p>
            <p className="muted">
              등록: {dateLabel(item.created_at)} · 최근 사용: {dateLabel(item.last_used_at)} (서울
              기준)
            </p>
            {confirming === item.id ? (
              <div role="group" aria-label={`${item.label} 패스키 해제 확인`}>
                <p>
                  이 패스키의 SallimBook 로그인을 해제할까요? 인증기 자체의 저장 항목은 별도로
                  관리해 주세요.
                </p>
                <div className="form-actions">
                  <button
                    type="button"
                    disabled={busy || loading || Boolean(error)}
                    onClick={() => void revoke(item)}
                  >
                    패스키 해제 확인
                  </button>
                  <button type="button" disabled={busy} onClick={() => setConfirming(null)}>
                    취소
                  </button>
                </div>
              </div>
            ) : (
              <button
                type="button"
                disabled={busy || loading || Boolean(error)}
                aria-label={`${item.label} 패스키 해제`}
                onClick={() => {
                  setActionError(null);
                  setConfirming(item.id);
                }}
              >
                패스키 해제
              </button>
            )}
          </li>
        ))}
      </ul>
      {cursor && (
        <button type="button" disabled={loading || busy} onClick={() => void load(cursor)}>
          패스키 더 보기
        </button>
      )}
    </section>
  );
}

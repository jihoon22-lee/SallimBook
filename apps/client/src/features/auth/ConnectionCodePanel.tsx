import { useEffect, useRef, useState } from "react";
import type { components } from "@sallimbook/api-client";
import { toApiError } from "../../platform/api";
import type { ApiError } from "../../platform/api";
import { isNativeAuth } from "../../platform/nativeAuth";
import { AuthError, useMounted } from "./AuthFeedback";
import { useAuth } from "./AuthProvider";
import { useAuthCeremony } from "./useAuthCeremony";

export function ConnectionCodePanel({ onLegacyInvitation }: { onLegacyInvitation: () => void }) {
  const { createConnectionCode, createNativeConnectionCode } = useAuth();
  const native = isNativeAuth();
  const mounted = useMounted();
  const ceremony = useAuthCeremony();
  const generation = useRef(0);
  const [busy, setBusy] = useState(false),
    [created, setCreated] = useState(false),
    [revealed, setRevealed] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [code, setCode] = useState<components["schemas"]["ConnectionCodeResponse"] | null>(null);
  useEffect(() => {
    const clear = () => {
      generation.current++;
      setCode(null);
      setRevealed(false);
      setCreated(false);
    };
    const hidden = () => {
      if (document.visibilityState !== "visible") clear();
    };
    window.addEventListener("pagehide", clear);
    document.addEventListener("visibilitychange", hidden);
    return () => {
      generation.current++;
      window.removeEventListener("pagehide", clear);
      document.removeEventListener("visibilitychange", hidden);
    };
  }, []);
  useEffect(() => {
    if (!code) return;
    const remaining = Date.parse(code.expires_at) - Date.now();
    const timer = window.setTimeout(
      () => {
        setCode(null);
        setRevealed(false);
      },
      Number.isFinite(remaining)
        ? Math.max(0, Math.min(remaining, revealed ? 30_000 : 900_000))
        : 0,
    );
    return () => window.clearTimeout(timer);
  }, [code, revealed]);

  async function create() {
    if (busy) return;
    const current = ++generation.current;
    setBusy(true);
    setError(null);
    setCode(null);
    setCreated(false);
    setRevealed(false);
    try {
      if (native) {
        const done = await createNativeConnectionCode();
        if (mounted.current && generation.current === current) setCreated(done);
      } else {
        const result = await ceremony.run(createConnectionCode);
        if (
          mounted.current &&
          generation.current === current &&
          document.visibilityState === "visible"
        )
          setCode(result);
      }
    } catch (failure) {
      if (mounted.current && generation.current === current) setError(toApiError(failure));
    } finally {
      if (mounted.current) setBusy(false);
    }
  }
  return (
    <section className="card" aria-labelledby="connection-code-title">
      <h2 id="connection-code-title">배우자와 연결하기</h2>
      <p>
        8자리 연결 코드를 배우자에게 전달해 주세요. 배우자는 자신의 기기에서 배우자 연결을 열고
        코드·이름·비밀번호를 입력하면 돼요.
      </p>
      <p className="muted">
        코드는 15분 동안 한 번 사용할 수 있어요. 새 코드를 만들면 이전 코드는 사용할 수 없어요.
      </p>
      {error?.code === "LOGIN_UNAVAILABLE" ? (
        <div role="alert">
          <p>
            기존 계정의 로그인 이름과 겹쳐 연결 코드를 만들 수 없어요. 기존 초대 방식으로 다른
            로그인 이름을 정해 주세요.
          </p>
          <button type="button" onClick={onLegacyInvitation}>
            기존 초대 방식으로 연결
          </button>
        </div>
      ) : error?.code === "REQUEST_CANCELLED" ? (
        <p role="alert">
          코드 생성 요청 대기를 중단했어요. 코드가 생성됐을 수 있어요. 새 코드를 만들면 이전 코드는
          사용할 수 없어요.
        </p>
      ) : (
        <AuthError error={error} />
      )}
      <button type="button" disabled={busy} onClick={() => void create()}>
        {busy ? "연결 코드 준비 중…" : "배우자 연결 코드 만들기"}
      </button>
      {busy && !native && (
        <button type="button" onClick={ceremony.cancel}>
          요청 대기 중단
        </button>
      )}
      {created && (
        <p role="status">연결 코드를 만들었어요. 코드 전달은 앱의 보호 화면에서 진행해 주세요.</p>
      )}
      {code && (
        <div className="invitation-result">
          <p role="status">
            연결 코드를 만들었어요. 만료:{" "}
            {new Intl.DateTimeFormat("ko-KR", {
              timeZone: "Asia/Seoul",
              dateStyle: "medium",
              timeStyle: "short",
            }).format(new Date(code.expires_at))}{" "}
            (서울 기준)
          </p>
          {revealed ? (
            <>
              <output aria-label="생성된 배우자 연결 코드">{code.code}</output>
              <button
                type="button"
                onClick={() => {
                  setCode(null);
                  setRevealed(false);
                }}
              >
                연결 코드 가리기
              </button>
              <p className="muted">30초 후 화면에서 코드를 지워요.</p>
            </>
          ) : (
            <button type="button" onClick={() => setRevealed(true)}>
              연결 코드 보기
            </button>
          )}
        </div>
      )}
    </section>
  );
}

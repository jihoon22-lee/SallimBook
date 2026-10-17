import { useRef, useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router";
import { ApiError, toApiError } from "../../platform/api";
import { isNativeAuth } from "../../platform/nativeAuth";
import { nativeVault } from "../../platform/nativeVault";
import { AuthError, useMounted } from "../auth/AuthFeedback";
import { useAuth } from "../auth/AuthProvider";
import type { WebVaultRequest } from "./actions";
import { WebVaultAction } from "./WebVaultAction";

type Entry = WebVaultRequest | { action: "register-device" };
export function VaultActionLauncher({ children, onCompleted }: {
  children: (open: (request: Entry) => void, busy: boolean) => ReactNode;
  onCompleted?: () => void;
}) {
  const { domainApi } = useAuth(); const mounted = useMounted(); const flight = useRef(false);
  const [request, setRequest] = useState<WebVaultRequest | null>(null);
  const [busy, setBusy] = useState(false); const [error, setError] = useState<ApiError | null>(null); const [message, setMessage] = useState("");
  async function open(entry: Entry) {
    if (flight.current || request) return;
    setError(null); setMessage("");
    if (!isNativeAuth()) {
      if (entry.action === "register-device") { setError(new ApiError(0, "NATIVE_AUTH_UNAVAILABLE")); return; }
      flight.current = true; setRequest(entry); return;
    }
    flight.current = true; setBusy(true);
    try {
      const result = await domainApi.read(undefined, () => nativeVault.open(entry));
      if (!mounted.current) return;
      setMessage(result.status === "completed" ? "보관함 작업을 마쳤어요. 현재 상태를 다시 확인해요." : "보관함 작업을 취소했어요.");
      if (result.status === "completed") onCompleted?.();
    } catch (failure) {
      if (mounted.current) {
        const next = toApiError(failure);
        if (next.code === "REQUEST_CANCELLED") setMessage("보관함 작업을 취소했어요."); else setError(next);
      }
    } finally { flight.current = false; if (mounted.current) setBusy(false); }
  }
  return <>{children((entry) => { void open(entry); }, busy || request !== null)}
    {error?.code === "NATIVE_AUTH_UNAVAILABLE" ? <p role="alert">이 기기에서 보호된 보관함 화면을 열 수 없어요. 앱의 지원 상태를 확인해 주세요.</p> : <AuthError error={error} />}
    {message && <p role="status">{message}</p>}
    {busy && <p role="status">보호된 보관함 화면에서 작업하고 있어요.</p>}
    {request && <WebVaultAction request={request} onClose={() => { flight.current = false; setRequest(null); }} onCompleted={() => { flight.current = false; setRequest(null); setMessage("보관함 작업을 마쳤어요. 현재 상태를 다시 확인해요."); onCompleted?.(); }} />}
  </>;
}

export function CardVaultActions({ cardId, onCompleted }: { cardId: string; onCompleted?: () => void }) {
  const native = isNativeAuth();
  return <section className="card" aria-labelledby={`vault-card-${cardId}`}><h2 id={`vault-card-${cardId}`}>카드 보관함</h2>
    <p>유효기간 **/** · CVC/CVV ***</p><p>전체 번호와 유효기간은 별도 인증 후 보호된 화면에서 확인해요. 카드 사용 종료와 비밀 제거는 별도 작업이에요.</p>
    <VaultActionLauncher onCompleted={onCompleted}>{(open, busy) => <div className="form-actions">
      <button disabled={busy} onClick={() => open({ action: "view", cardId })}>전체 번호·유효기간 열람</button>
      <button disabled={busy} onClick={() => open({ action: "edit", cardId })}>카드 비밀 등록·수정</button>
      <button className="secondary-button" disabled={busy} onClick={() => open({ action: "purge", cardId })}>카드 비밀 제거</button>
    </div>}</VaultActionLauncher>
    <p className="muted">{native ? "CVC/CVV는 Android 기기 안에서만 보관하며 새 기기에서 다시 입력해야 해요. 현재 보안 검증 전이라 입력·열람·삭제 기능은 비활성 상태예요." : "CVC/CVV는 PC 웹에서 입력·열람·저장하지 않아요. 웹에서는 화면 캡처를 막을 수 없으니 주변을 확인해 주세요."}</p>
    <Link to="/vault">보관함 설정·공유·복구</Link>
  </section>;
}

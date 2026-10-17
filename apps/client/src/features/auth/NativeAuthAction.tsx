import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { ApiError, toApiError } from "../../platform/api";
import { nativeAuth } from "../../platform/nativeAuth";
import { AuthError, useMounted } from "./AuthFeedback";
import { useAuth } from "./AuthProvider";

export function NativeAuthAction({ mode }: { mode: "login" | "accept" | "invite" }) {
  const { loginNative } = useAuth();
  const mounted = useMounted();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [done, setDone] = useState(false);
  const label = mode === "login" ? "앱에서 로그인" : mode === "accept" ? "초대 수락하고 계정 등록" : "초대 만들기";

  async function start() {
    if (busy) return;
    setBusy(true); setError(null); setDone(false);
    try {
      if (mode === "login") {
        const signedIn = await loginNative();
        if (signedIn && mounted.current) navigate("/settings/auth", { replace: true });
      } else {
        const result = mode === "accept" ? await nativeAuth.acceptInvitation() : await nativeAuth.createInvitation();
        if (mounted.current && result.status !== "cancelled") setDone(true);
      }
    } catch (failure) { if (mounted.current) setError(toApiError(failure)); }
    finally { if (mounted.current) setBusy(false); }
  }

  return <section className="card">
    <h2>{mode === "invite" ? "함께 쓸 구성원 초대" : mode === "accept" ? "초대로 계정 등록" : "계정 로그인"}</h2>
    <p>{mode === "invite" ? "초대할 로그인 이름을 정하고, 생성된 코드를 함께 쓸 사람에게 전달해 주세요." : mode === "accept" ? "받은 초대 코드와 새 비밀번호를 다음 화면에 입력해 주세요." : "다음 화면에서 로그인 이름과 비밀번호를 입력해 주세요."}</p>
    <AuthError error={error} />
    <button type="button" disabled={busy} onClick={() => void start()}>{busy ? "인증 화면 사용 중…" : label}</button>
    {done && <p role="status">{mode === "accept" ? "계정 등록을 마쳤어요. 초대받은 로그인 이름으로 로그인해 주세요." : "초대를 만들었어요. 코드 전달 여부는 초대 화면에서 확인해 주세요."}</p>}
    {mode === "accept" && done && <Link className="button-link" to="/login">로그인하기</Link>}
    {mode === "login" && <p><Link to="/onboarding">초대 코드로 계정 등록</Link></p>}
  </section>;
}

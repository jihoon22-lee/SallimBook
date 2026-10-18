import { useEffect, useRef } from "react";
import { Link } from "react-router";
import { ApiError } from "../../platform/api";
import { useAuth } from "./AuthProvider";

export function authErrorMessage(error: ApiError, login = false): string {
  if (login && error.status === 401) return "로그인 이름이나 비밀번호를 확인해 주세요.";
  switch (error.code) {
    case "NETWORK_UNAVAILABLE": return "서버 연결을 확인하지 못했어요. 연결 상태를 확인한 뒤 다시 시도해 주세요.";
    case "UNAUTHENTICATED": return "로그인이 만료되었거나 필요해요. 다시 로그인해 주세요.";
    case "REAUTHENTICATION_REQUIRED": return "다시 로그인한 후 진행해 주세요. 패스키 등록과 해제에는 5분 이내 로그인이 필요해요. 초대와 기기 해제는 패스키로 해당 작업만 확인할 수도 있어요.";
    case "PASSKEY_UNSUPPORTED": return "이 브라우저에서는 패스키를 사용할 수 없어요. 최신 브라우저의 HTTPS 주소에서 다시 시도하거나 비밀번호로 로그인해 주세요.";
    case "PASSKEY_CANCELLED": return "패스키 인증을 완료하지 않았어요. 준비되면 다시 시도해 주세요.";
    case "PASSKEY_EXPIRED": return "패스키 요청 시간이 지났어요. 다시 시작해 주세요.";
    case "PASSKEY_CONFIGURATION_INVALID":
    case "PASSKEYS_DISABLED": return "이 주소의 패스키 연결이 설정되지 않았어요. 비밀번호 로그인을 이용해 주세요.";
    case "PASSKEY_VERIFICATION_FAILED":
    case "PASSKEY_FAILED": return "패스키를 확인하지 못했어요. 이 계정에 등록된 패스키로 다시 시도해 주세요.";
    case "PASSKEY_REQUIRED": return "먼저 패스키를 등록하거나 다시 로그인한 뒤 진행해 주세요.";
    case "CREDENTIAL_UNAVAILABLE": return "이 패스키를 등록할 수 없어요. 등록 목록을 확인하거나 다른 패스키를 선택해 주세요.";
    case "STEP_UP_REQUIRED": return "이 작업의 인증이 만료되었거나 사용할 수 없어요. 작업과 대상을 확인하고 다시 인증해 주세요.";
    case "REAUTHENTICATION_FAILED": return "현재 계정의 비밀번호를 다시 확인해 주세요. 기존 로그인은 유지돼요.";
    case "CSRF_FAILED": return "인증 상태가 다시 변경되어 요청을 완료하지 않았어요. 세션을 다시 확인한 뒤 시도해 주세요.";
    case "VERSION_CONFLICT": return "정보가 다른 곳에서 변경됐어요. 목록을 다시 불러온 뒤 확인해 주세요.";
    case "SETUP_UNAVAILABLE": return "지금은 새 가계를 시작할 수 없어요. 이미 계정이 있다면 로그인하거나 배우자 연결 코드를 확인해 주세요.";
    case "SETUP_COMPLETE": return "이미 가계가 시작되었어요. 만든 계정으로 로그인하거나 배우자 연결 코드를 받아 주세요.";
    case "INVALID_CONNECTION_CODE": return "연결 코드가 맞지 않거나 만료되었어요. 배우자에게 새 코드를 확인해 주세요.";
    case "HOUSEHOLD_FULL": return "이 가계에는 이미 두 계정이 등록되어 있어요.";
    case "LOGIN_UNAVAILABLE": return "이 로그인 이름은 사용할 수 없어요. 다른 이름을 입력해 주세요.";
    case "INVALID_INVITATION": return "초대 코드가 만료되었거나 사용할 수 없어요. 새 초대를 확인해 주세요.";
    case "REGISTRATION_CONFLICT": return "등록 상태가 변경됐어요. 초대를 만든 사람에게 확인해 주세요.";
    case "RATE_LIMITED": return "요청이 많아 잠시 기다려야 해요. 잠시 후 다시 시도해 주세요.";
    case "FORBIDDEN": return "이 작업을 할 권한이 없어요.";
    case "NOT_FOUND": return "해당 기기를 찾을 수 없어요. 목록을 다시 확인해 주세요.";
    case "ORIGIN_REJECTED": return "이 주소에서는 인증 요청을 사용할 수 없어요. 설정된 SallimBook 주소로 접속해 주세요.";
    case "NATIVE_AUTH_UNAVAILABLE": return "앱의 네이티브 인증을 준비하고 있어요. 지금은 앱에서 로그인할 수 없어요.";
    case "NATIVE_KEY_INVALIDATED": return "이 기기의 로그인 정보를 사용할 수 없어요. 다시 로그인해 주세요.";
    case "ALREADY_AUTHENTICATED": return "현재 계정에서 로그아웃한 뒤 초대를 수락해 주세요.";
    case "VALIDATION_ERROR": return "입력 형식과 필수 항목을 확인해 주세요.";
    case "REQUEST_CANCELLED": return "인증 상태가 변경되어 이전 요청을 중단했어요.";
    default: return error.status === 422 ? "입력 형식과 필수 항목을 확인해 주세요." : "요청을 완료하지 못했어요. 잠시 후 다시 시도해 주세요.";
  }
}

export function AuthError({ error, login = false }: { error: ApiError | null; login?: boolean }) {
  const { reloadSession } = useAuth();
  if (!error) return null;
  return <div className="auth-message" role="alert">
    <p>{authErrorMessage(error, login)}</p>
    {error.code === "REAUTHENTICATION_REQUIRED" && <Link className="button-link" to="/login">다시 로그인</Link>}
    {error.code === "CSRF_FAILED" && <button type="button" onClick={() => void reloadSession()}>세션 다시 확인</button>}
  </div>;
}

export function NativeAuthUnavailable() {
  return <section className="card auth-message" aria-labelledby="native-auth-title">
    <span className="status-chip">앱 인증 준비 중</span>
    <h2 id="native-auth-title">네이티브 인증을 준비하고 있어요</h2>
    <p>현재 앱에서는 로그인·초대 수락·세션 관리를 사용할 수 없어요. 이 화면에서 비밀번호나 인증 정보를 입력받지 않아요.</p>
    <p className="muted">웹 계정 관리는 설정된 SallimBook 웹 주소에서 이용할 수 있어요.</p>
  </section>;
}

export function SessionStatus() {
  const { state, reloadSession } = useAuth();
  if (state.status === "native-unavailable") return <NativeAuthUnavailable />;
  if (state.status === "loading") return <p role="status">로그인 상태를 확인하고 있어요.</p>;
  if (state.status === "error") return <section className="card">
    <AuthError error={state.error} />
    <button type="button" onClick={() => void reloadSession()}>로그인 상태 다시 확인</button>
  </section>;
  if (state.status === "signed-out") return <section className="card"><h2>로그인이 필요해요</h2>
    {state.remoteRevocationUnconfirmed && <p role="status">이 기기에서는 로그아웃했어요. 서버 연결을 확인하지 못해 다른 기기에서 이 기기의 연결 해제를 확인해 주세요.</p>}
    <p>계정과 등록 기기를 확인하려면 로그인해 주세요.</p><Link className="button-link" to="/login">로그인하기</Link></section>;
  return null;
}

export function clearSensitiveFields(form: HTMLFormElement | null) {
  form?.querySelectorAll<HTMLInputElement>('input[type="password"]').forEach((input) => { input.value = ""; });
}

export function useSensitiveForm() {
  const form = useRef<HTMLFormElement>(null);
  useEffect(() => {
    const clear = () => clearSensitiveFields(form.current);
    const onVisibility = () => { if (document.visibilityState !== "visible") clear(); };
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("pagehide", clear);
    return () => {
      clear();
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("pagehide", clear);
    };
  }, []);
  return form;
}

export function useMounted() {
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  return mounted;
}

import { useEffect, useState } from "react";
import { Link } from "react-router";
import { toApiError } from "../../platform/api";
import type { ApiError } from "../../platform/api";
import { AuthError } from "./AuthFeedback";
import { useAuth } from "./AuthProvider";

export function useSetupAvailability() {
  const { getSetupStatus } = useAuth();
  const [available, setAvailable] = useState<boolean | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setAvailable(null);
    setError(null);
    void getSetupStatus(controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) setAvailable(result.available);
      })
      .catch((failure) => {
        if (!controller.signal.aborted) setError(toApiError(failure));
      });
    return () => controller.abort();
  }, [getSetupStatus, attempt]);
  return { available, error, retry: () => setAttempt((value) => value + 1) };
}

export function OnboardingChoices({
  loginLink = false,
  compact = false,
}: {
  loginLink?: boolean;
  compact?: boolean;
}) {
  const setup = useSetupAvailability();
  return (
    <section
      className={`card onboarding-choices${compact ? " compact" : ""}`}
      aria-labelledby="first-start-title"
    >
      <h2 id="first-start-title">둘이 함께 시작해요</h2>
      {setup.available === null && !setup.error && (
        <p role="status">가계 시작 상태를 확인하고 있어요.</p>
      )}
      <AuthError error={setup.error} />
      {setup.error && (
        <button type="button" onClick={setup.retry}>
          가계 시작 상태 다시 확인
        </button>
      )}
      {setup.available === true && (
        <>
          <p>처음이라면 이름과 비밀번호로 우리 가계를 시작해요. 등록하면 바로 로그인돼요.</p>
          <Link className="button-link" to="/onboarding">
            우리 가계 시작하기
          </Link>
        </>
      )}
      {setup.available === false && (
        <p>이미 시작한 가계가 있다면 로그인하거나 배우자에게 받은 연결 코드를 입력해 주세요.</p>
      )}
      <p>
        <Link className="button-link" to="/onboarding/connect">
          배우자 연결
        </Link>
      </p>
      {loginLink && <Link to="/login">이미 계정이 있어요 · 로그인</Link>}
    </section>
  );
}

export function SignedOutWelcome() {
  const { state } = useAuth();
  return state.status === "signed-out" ? <OnboardingChoices loginLink /> : null;
}

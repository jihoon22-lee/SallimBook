import { installedAppInfo } from "../../platform/appInfo";
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { version } from "../../../package.json";
import { toApiError } from "../../platform/api";
import type { ApiError } from "../../platform/api";
import { isNativeAuth, nativeAuth } from "../../platform/nativeAuth";
import { RelatedLinks } from "../../shared/RelatedLinks";
import { AuthError, SessionStatus } from "../auth/AuthFeedback";
import { useAuth } from "../auth/AuthProvider";
import { MemberLoadError, useHouseholdMembers } from "../finance/FinanceSupport";

function HouseholdSummary() {
  const household = useHouseholdMembers();
  return (
    <section className="card">
      <h2>함께 쓰는 가계</h2>
      <p>
        두 계정이 하나의 가계를 함께 사용해요. 로그인 계정과 금융상품의 소유자는 별도로 관리해요.
      </p>
      <MemberLoadError error={household.error} retry={household.retry} />
      {household.loading && <p role="status">가계 구성원을 확인하고 있어요.</p>}
      {!household.loading && !household.error && (
        <ul className="record-list">
          {household.members.map((member) => (
            <li key={member.member_id}>
              <p>
                {member.display_name} · {member.role === "owner" ? "가계 관리자" : "가계 구성원"}
              </p>
            </li>
          ))}
        </ul>
      )}
      <Link to="/settings/auth">구성원 초대와 기기 관리</Link>
    </section>
  );
}

function AppVersion() {
  const [info, setInfo] = useState<{ version: string; build: string } | null>(null);
  const [failed, setFailed] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    setFailed(false);
    void installedAppInfo()
      .then((value) => {
        if (active) setInfo(value);
      })
      .catch(() => {
        if (active) setFailed(true);
      });
    return () => {
      active = false;
    };
  }, [retry]);
  return (
    <section className="card">
      <h2>앱 정보</h2>
      <p>SallimBook · 웹 클라이언트 버전 {version}</p>
      {info && (
        <p>
          Android 앱 버전 {info.version} · 빌드 {info.build}
        </p>
      )}
      {failed && (
        <>
          <p role="alert">Android 앱 버전을 확인하지 못했어요.</p>
          <button type="button" onClick={() => setRetry((value) => value + 1)}>
            앱 버전 다시 확인
          </button>
        </>
      )}
    </section>
  );
}

export function SettingsPage() {
  const { state } = useAuth();
  const native = isNativeAuth();
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<ApiError | null>(null);
  async function lock() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await nativeAuth.lock();
    } catch (failure) {
      setError(toApiError(failure));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="intro">
        <p className="eyebrow">함께 쓰는 환경</p>
        <h1>설정</h1>
        <p>계정과 기기, 공동 가계, 보호된 정보와 자료 기록을 관리해요.</p>
      </div>
      <RelatedLinks
        links={[
          {
            to: "/settings/auth",
            label: "계정과 기기",
            description: "로그인 계정·패스키·등록 기기·구성원 초대",
          },
          {
            to: "/settings/people",
            label: "가족 관리",
            description: "보험의 환자·피보험자와 비로그인 가족",
          },
          { to: "/vault", label: "보관함", description: "보호된 카드 정보·복구·기기 상태" },
          { to: "/exports", label: "자료 내보내기", description: "JSON·CSV와 선택 문서 ZIP" },
          {
            to: "/activity",
            label: "최근 작업 이력",
            description: "구성원·기간·대상별 작업 기록",
          },
          {
            to: "/settings/audit",
            label: "감사 이력",
            description: "구성원·기간·대상별 작업 기록",
          },
        ]}
      />
      {state.status === "authenticated" ? (
        <HouseholdSummary key={state.member.member_id} />
      ) : (
        <SessionStatus />
      )}
      <section className="card">
        <h2>잠금과 로그인</h2>
        {native ? (
          <>
            <p>
              앱을 잠그면 이 기기의 보호된 화면과 세션 접근을 막아요. 다시 사용하려면 기기에 등록된
              인증수단으로 확인해 주세요.
            </p>
            <AuthError error={error} />
            <button type="button" disabled={busy} onClick={() => void lock()}>
              {busy ? "잠그는 중…" : "이 Android 앱 잠그기"}
            </button>
          </>
        ) : (
          <p>
            웹 보관함은 보호 화면을 닫으면 비밀과 키를 정리해요. 공용 PC에서 사용을 마쳤다면 계정과
            기기에서 로그아웃해 주세요.
          </p>
        )}
        <RelatedLinks
          links={[
            { to: "/login", label: "로그인·재인증" },
            state.status === "authenticated"
              ? { to: "/settings/auth", label: "가계 구성원 관리" }
              : { to: "/onboarding", label: "초대받은 계정 등록" },
          ]}
        />
      </section>
      <AppVersion />
    </>
  );
}

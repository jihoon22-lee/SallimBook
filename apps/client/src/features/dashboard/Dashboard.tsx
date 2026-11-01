import { HouseholdOverview } from "./HouseholdOverview";
import { HomeAttention } from "./HomeAttention";
import { Link } from "react-router";
import { useState, type ReactNode } from "react";
import { MonthPicker, useMonth } from "../../shared/MonthContext";
import { RetryScope, useRetryReport } from "../../shared/RetryFailed";
import { useAuth } from "../auth/AuthProvider";
import { HomeAssetSummary } from "./HomeAssetSummary";
import { TodayConsumables } from "../homecare/TodayConsumables";
import { HomeSecondary } from "./HomeSecondary";
import { useHouseholdOverview } from "./overviewApi";

/** One status read feeds the plan margin and the holdings; each part still loads on its own. */
function SignedInHome() {
  const { month } = useMonth();
  const overview = useHouseholdOverview(month);
  const quiet = useRetryReport("household-overview", overview.error, overview.reload);
  return (
    <>
      <HomeSecondary overview={overview} overviewQuiet={quiet} />
      <HouseholdOverview overview={overview} quiet={quiet} />
      <TodayConsumables compact />
    </>
  );
}

export function Dashboard({ welcome }: { welcome?: ReactNode }) {
  const { state } = useAuth();
  const [history, setHistory] = useState(false);
  const [attention, setAttention] = useState(false);
  return (
    <>
      <div className="dashboard-heading">
        <div className="intro">
          <p className="eyebrow">우리 집의 기록</p>
          <h1>오늘의 살림</h1>
          <p>등록한 기록으로 지금 우리 집 살림을 한눈에.</p>
        </div>
        <MonthPicker />
      </div>
      {welcome}
      {state.status === "authenticated" ? (
        <RetryScope label="홈 다시 불러오기">
          <SignedInHome />
        </RetryScope>
      ) : (
        <>
          <HomeSecondary />
          <HouseholdOverview />
          <TodayConsumables compact />
        </>
      )}
      <details
        className="card dashboard-history"
        onToggle={(event) => setHistory(event.currentTarget.open)}
      >
        <summary>월별 자산 변화·기록 관리</summary>
        {history && <HomeAssetSummary />}
      </details>
      <details
        className="card dashboard-history"
        onToggle={(event) => setAttention(event.currentTarget.open)}
      >
        <summary>예정일과 진행 중인 기록 살펴보기</summary>
        {attention && <HomeAttention />}
      </details>
      <p>
        <Link to="/activity">함께한 최근 작업 보기</Link>
      </p>
    </>
  );
}

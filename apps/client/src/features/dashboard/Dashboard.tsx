import { HouseholdOverview } from "./HouseholdOverview";
import { HomeAttention } from "./HomeAttention";
import { Link } from "react-router";
import { useState, type ReactNode } from "react";
import { MonthPicker } from "../../shared/MonthContext";
import { HomeAssetSummary } from "./HomeAssetSummary";
import { TodayConsumables } from "../homecare/TodayConsumables";
import { HomeSecondary } from "./HomeSecondary";

export function Dashboard({ welcome }: { welcome?: ReactNode }) {
  const [history, setHistory] = useState(false);
  const [attention, setAttention] = useState(false);
  return (
    <>
      <div className="dashboard-heading">
        <div className="intro">
          <p className="eyebrow">우리 집의 기록</p>
          <h1>오늘의 살림</h1>
          <p>자산과 수입·지출, 우리 집 물건을 한눈에.</p>
        </div>
        <MonthPicker />
      </div>
      {welcome}
      <HomeSecondary />
      <HouseholdOverview />
      <TodayConsumables compact />
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

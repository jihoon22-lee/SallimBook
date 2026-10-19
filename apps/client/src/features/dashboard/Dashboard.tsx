import { MonthPicker } from "../../shared/MonthContext";
import { HomeAssetSummary } from "./HomeAssetSummary";
import { TodayConsumables } from "../homecare/TodayConsumables";
import { HomeSecondary } from "./HomeSecondary";

export function Dashboard() {
  return (
    <>
      <div className="dashboard-heading">
        <div className="intro">
          <p className="eyebrow">우리 집의 기록</p>
          <h1>오늘의 살림</h1>
          <p>월별 자산부터 생활 속 작은 물건까지, 한곳에서 차근차근.</p>
        </div>
        <MonthPicker />
      </div>
      <div className="dashboard-grid">
        <HomeAssetSummary />
        <TodayConsumables compact />
      </div>
      <HomeSecondary />
    </>
  );
}

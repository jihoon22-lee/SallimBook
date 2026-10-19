import type { PlannedScreen } from "../../shared/screens";

export const assetScreens: PlannedScreen[] = [
  {
    id: "UI-04",
    path: "/assets",
    title: "자산과 부채",
    group: "assets",
    description: "월별 잔액과 평가액을 함께 확인하는 공간이에요.",
    upcoming: "부동산·보증금·금융자산·부채 등록과 소유자별 확인 기능을 준비하고 있어요.",
    parent: { to: "/", label: "홈" },
    monthly: true,
    links: [
      { to: "/accounts", label: "계좌 관리", description: "은행·증권·연금저축·IRP·DC·ISA" },
      { to: "/assets/compare", label: "월간 비교", description: "자산의 변화와 비교 범위" },
    ],
  },
  {
    id: "UI-05",
    path: "/assets/:id",
    title: "자산 상세",
    group: "assets",
    description: "자산의 지분, 평가 기준과 연결 계좌를 확인하는 공간이에요.",
    upcoming:
      "자산 상세 조회와 월별 추이 기능을 준비하고 있어요. 아직 이 경로의 자산을 조회하지 않았어요.",
    parent: { to: "/assets", label: "자산 목록" },
  },
  {
    id: "UI-06",
    path: "/assets/months/:month",
    title: "월별 자산 확인",
    group: "assets",
    description: "해당 월의 잔액·평가액과 기준일을 확인하는 공간이에요.",
    upcoming:
      "전월값 불러오기, 변동 없음 확인, 확정·정정 기능을 준비하고 있어요. 미입력 금액을 0원으로 채우지 않아요.",
    parent: { to: "/assets", label: "자산 목록" },
  },
  {
    id: "UI-07",
    path: "/assets/compare",
    title: "월간 자산 비교",
    group: "assets",
    description: "순자산의 변화와 비교 대상의 변화를 함께 살펴보는 공간이에요.",
    upcoming:
      "월별 비교 기능을 준비하고 있어요. 전월값이 미확인인 항목과 새로 등록한 항목을 구분해 안내할 예정이에요.",
    parent: { to: "/assets", label: "자산 목록" },
    monthly: true,
  },
];

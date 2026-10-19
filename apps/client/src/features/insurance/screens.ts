import type { PlannedScreen } from "../../shared/screens";

export const insuranceScreens: PlannedScreen[] = [
  {
    id: "insurance",
    path: "/insurance",
    title: "보험",
    group: "insurance",
    description: "계약부터 진료·약국, 비용·청구·실제 지급까지 함께 기록해요.",
    upcoming: "보험 계약과 사건별 진료 트리, 수동 청구·지급 기록 기능을 준비하고 있어요.",
    parent: { to: "/", label: "홈" },
    links: [
      { to: "/insurance/policies", label: "보험 계약", description: "계약·보장·보험료" },
      { to: "/insurance/cases", label: "보험 사건", description: "진료·약국·비용·청구·지급" },
      {
        to: "/insurance/payouts/new",
        label: "보험금 수령 입력 안내",
        description: "실제 입금과 사건별 배분",
      },
    ],
  },
  {
    id: "UI-17",
    path: "/insurance/policies",
    title: "보험 계약",
    group: "insurance",
    description: "피보험자별 보장과 납입 상태를 확인하는 공간이에요.",
    upcoming: "보험 계약·보장·문서 등록과 보험료 연결 기능을 준비하고 있어요.",
    parent: { to: "/insurance", label: "보험" },
  },
  {
    id: "UI-18",
    path: "/insurance/policies/:id",
    title: "보험 계약 상세",
    group: "insurance",
    description: "계약·보장·납부 규칙과 연결된 사건을 살펴보는 공간이에요.",
    upcoming:
      "보험 계약 상세와 관련 문서 조회를 준비하고 있어요. 아직 이 경로의 계약을 조회하지 않았어요.",
    parent: { to: "/insurance/policies", label: "보험 계약 목록" },
  },
  {
    id: "UI-19",
    path: "/insurance/cases",
    title: "보험 사건",
    group: "insurance",
    description: "사건별 치료·청구 상태와 실제 비용을 함께 확인해요.",
    upcoming: "사건 등록과 진료·약국 트리, 비용·청구·지급의 수동 기록을 준비하고 있어요.",
    parent: { to: "/insurance", label: "보험" },
    links: [{ to: "/insurance/payouts/new", label: "보험금 수령 입력 안내" }],
  },
  {
    id: "UI-20",
    path: "/insurance/cases/:id",
    title: "보험 사건 상세",
    group: "insurance",
    description: "진료·약국 트리에서 비용, 청구와 지급을 연결하는 공간이에요.",
    upcoming:
      "사건 상세와 정산 기능을 준비하고 있어요. 같은 비용을 여러 청구에 연결해도 중복 합산하지 않아요.",
    parent: { to: "/insurance/cases", label: "보험 사건 목록" },
  },
  {
    id: "UI-21",
    path: "/insurance/payouts/new",
    title: "보험금 수령 입력",
    group: "insurance",
    description: "실제로 입금된 보험금과 사건·청구별 배분을 기록하는 공간이에요.",
    upcoming:
      "보험금 수령·반환 입력 기능을 준비하고 있어요. 청구 내역을 몰라도 사건에 수령부터 기록할 수 있도록 만들고 있어요.",
    parent: { to: "/insurance/cases", label: "보험 사건 목록" },
  },
];

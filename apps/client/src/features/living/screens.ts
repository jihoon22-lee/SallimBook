import type { PlannedScreen } from "../../shared/screens";

export const livingScreens: PlannedScreen[] = [
  {
    id: "living", path: "/living", title: "생활비", group: "living",
    description: "들어온 수입과 정기적으로 납부할 금액을 차근차근 기록해요.",
    upcoming: "수입·고정 납부·카드 관리 기능을 준비하고 있어요. 모든 기록은 직접 입력할 수 있도록 만들고 있어요.",
    parent: { to: "/", label: "홈" },
    links: [{ to: "/income", label: "월간 수입", description: "구성원별 수입과 보험금 유입" }, { to: "/fixed-payments", label: "고정 납부", description: "예정 금액과 실제 납부 기록" }, { to: "/cards", label: "카드 관리", description: "카드 정보와 연결된 정기결제" }],
  },
  {
    id: "UI-10", path: "/income", title: "월간 수입", group: "living",
    description: "등록 기준으로 구성원별 수입과 보험금 유입을 나누어 확인해요.",
    upcoming: "수입 조회·입력 기능을 준비하고 있어요. 보험금 수령은 연결된 사건에서 관리하며 중복으로 기록하지 않아요.",
    parent: { to: "/living", label: "생활비" }, monthly: true,
    links: [{ to: "/income/new", label: "수입 입력 안내" }, { to: "/insurance/cases", label: "보험 사건 보기" }],
  },
  {
    id: "UI-11", path: "/income/new", title: "수입 입력", group: "living",
    description: "월합계 또는 실제 입금일 기준으로 수입을 기록할 수 있도록 준비하고 있어요.",
    upcoming: "입력·저장 기능은 아직 연결되지 않았어요. 종류·구성원·수령 계좌·금액을 기록하는 화면이 이곳에 마련될 예정이에요.",
    parent: { to: "/income", label: "수입 목록" },
  },
  {
    id: "UI-12", path: "/fixed-payments", title: "고정 납부", group: "living",
    description: "등록된 고정 납부의 예정과 실제 납부를 구분해 확인해요.",
    upcoming: "보험료·구독·통신비·대출 원리금과 연금 납입의 수동 기록을 준비하고 있어요. 원금 상환과 연금 납입은 소비 비용과 구분해요.",
    parent: { to: "/living", label: "생활비" }, monthly: true,
  },
  {
    id: "UI-13", path: "/fixed-payments/:id", title: "고정 납부 상세", group: "living",
    description: "납부 규칙, 결제수단과 회차별 기록을 확인하는 공간이에요.",
    upcoming: "예정 금액과 실제 납부 내역 조회를 준비하고 있어요. 규칙 변경 시 과거 납부액은 유지해요.",
    parent: { to: "/fixed-payments", label: "고정 납부 목록" },
  },
];

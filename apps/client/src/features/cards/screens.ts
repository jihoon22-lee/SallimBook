import type { PlannedScreen } from "../../shared/screens";

export const cardScreens: PlannedScreen[] = [
  {
    id: "UI-14",
    path: "/cards",
    title: "카드 관리",
    group: "living",
    description: "함께 사용하는 카드와 연결된 정기결제를 확인하는 공간이에요.",
    upcoming:
      "카드 등록·수정·종료 기능을 준비하고 있어요. 일반 화면에는 카드번호의 마지막 네 자리만 표시할 예정이에요.",
    parent: { to: "/living", label: "생활비" },
    links: [{ to: "/vault", label: "보관함 안내" }],
  },
  {
    id: "UI-15",
    path: "/cards/:id",
    title: "카드 상세",
    group: "living",
    description: "카드 일반정보와 연결된 결제수단을 확인하는 공간이에요.",
    upcoming:
      "카드 상세 조회와 보호된 정보 보기 기능을 준비하고 있어요. 지금은 카드 정보를 입력하거나 열람할 수 없어요.",
    parent: { to: "/cards", label: "카드 목록" },
    links: [{ to: "/vault", label: "보관함 안내" }],
  },
];

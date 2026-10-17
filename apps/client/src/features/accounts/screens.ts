import type { PlannedScreen } from "../../shared/screens";

export const accountScreens: PlannedScreen[] = [
  {
    id: "UI-08", path: "/accounts", title: "계좌 관리", group: "assets",
    description: "은행·증권·연금저축·IRP·DC·ISA를 한곳에서 관리해요.",
    upcoming: "계좌 등록과 월 평가액 확인 기능을 준비하고 있어요. 자산과 연결된 계좌는 중복 합산하지 않아요.",
    parent: { to: "/assets", label: "자산" },
  },
  {
    id: "UI-09", path: "/accounts/:id", title: "계좌 상세", group: "assets",
    description: "계좌 정보와 월 평가액, 연결된 카드·수입을 확인하는 공간이에요.",
    upcoming: "계좌 상세 조회를 준비하고 있어요. 잔액은 별도 확인치이며, 수입·납부 기록으로 자동 변경하지 않아요.",
    parent: { to: "/accounts", label: "계좌 목록" },
  },
];

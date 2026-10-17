import type { PlannedScreen } from "../../shared/screens";

export const authScreens: PlannedScreen[] = [
  {
    id: "UI-01", path: "/login", title: "로그인", group: "more",
    description: "각자의 계정으로 하나의 공동 가계를 사용하는 공간이에요.",
    upcoming: "로그인과 패스키·초대 등록 기능을 준비하고 있어요. 현재 화면에서는 비밀번호나 개인정보를 입력받지 않아요.",
    parent: { to: "/", label: "홈" },
    links: [{ to: "/onboarding", label: "공동 가계 시작 안내" }],
  },
  {
    id: "UI-02", path: "/onboarding", title: "공동 가계 시작", group: "more",
    description: "두 계정으로 함께 쓸 공동 가계를 준비해요.",
    upcoming: "가계 생성, 두 번째 구성원 초대와 기기 등록 기능을 준비하고 있어요. 아직 계정이나 가계가 만들어지지 않아요.",
    parent: { to: "/login", label: "로그인 안내" },
  },
];

import type { PlannedScreen } from "../../shared/screens";

export const authScreens: PlannedScreen[] = [
  {
    id: "UI-01", path: "/login", title: "로그인", group: "more",
    description: "각자의 계정으로 하나의 공동 가계를 사용하는 공간이에요.",
    upcoming: "로그인·패스키와 첫 가계 시작·배우자 연결을 사용할 수 있어요.",
    parent: { to: "/", label: "홈" },
    links: [{ to: "/onboarding", label: "공동 가계 시작 안내" }],
  },
  {
    id: "UI-02", path: "/onboarding", title: "공동 가계 시작", group: "more",
    description: "두 계정으로 함께 쓸 공동 가계를 준비해요.",
    upcoming: "이름과 비밀번호로 첫 가계를 만들거나 배우자의 연결 코드로 같은 가계에 참여해요.",
    parent: { to: "/login", label: "로그인 안내" },
  },
];

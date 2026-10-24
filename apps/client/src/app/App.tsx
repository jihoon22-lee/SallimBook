import { PurchasePlanPage } from "../features/homecare/orders/PurchasePlanPage";
import {
  OrderListPage,
  OrderNewPage,
  OrderDetailPage,
} from "../features/homecare/orders/OrderPages";
import { ActivityPage } from "../features/audit/ActivityPage";
import { RecordActorsProvider } from "../shared/RecordActor";
import { useEffect, useLayoutEffect, useRef } from "react";
import { isNativeAuth, nativeAuth } from "../platform/nativeAuth";
import {
  Link,
  matchRoutes,
  NavLink,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useNavigationType,
} from "react-router";
import {
  AccountListPage,
  AccountNewPage,
  AccountDetailPage,
} from "../features/accounts/AccountPages";
import { accountScreens } from "../features/accounts/screens";
import { assetScreens } from "../features/assets/screens";
import { AssetComparisonPage } from "../features/assets/comparison/ComparisonPage";
import { AssetMonthPage } from "../features/assets/months/MonthPage";
import { AssetListPage, AssetNewPage, AssetDetailPage } from "../features/assets/AssetPages";
import { authScreens } from "../features/auth/screens";
import { Icon } from "../shared/Icon";
import type { IconName } from "../shared/Icon";
import { AuthProvider, useAuth } from "../features/auth/AuthProvider";
import { InvitationAcceptPage } from "../features/auth/InvitationAcceptPage";
import { OnboardingPage } from "../features/auth/OnboardingPage";
import { SignedOutWelcome } from "../features/auth/OnboardingEntry";
import { LoginPage } from "../features/auth/LoginPage";
import { SessionExpiredDialog } from "../features/auth/SessionExpiredDialog";
import { SessionSettings } from "../features/auth/SessionSettings";
import { CardListPage, CardNewPage, CardDetailPage } from "../features/cards/CardPages";
import { IncomeListPage, IncomeNewPage, IncomeDetailPage } from "../features/income/IncomePages";
import { IncomeConversionPage } from "../features/income/IncomeConversion";
import {
  FixedListPage,
  FixedDetailPage,
  RuleListPage,
  RuleNewPage,
  RuleDetailPage,
} from "../features/fixed/FixedPages";
import { LivingPage } from "../features/living/LivingPage";
import {
  ApplianceListPage,
  ApplianceNewPage,
  ApplianceDetailPage,
} from "../features/homecare/AppliancePages";
import {
  ConsumableListPage,
  ConsumableNewPage,
  ConsumableDetailPage,
} from "../features/homecare/ConsumablePages";
import { DeviceDetailPage } from "../features/homecare/DeviceLinks";
import { StockNewPage, StockDetailPage } from "../features/homecare/StockPages";
import { ReplacementDetailPage } from "../features/homecare/ReplacementPages";
import { Dashboard } from "../features/dashboard/Dashboard";
import { householdScreens } from "../features/household/screens";
import { InsuranceHome } from "../features/insurance/InsuranceHome";
import {
  PolicyListPage,
  PolicyNewPage,
  PolicyDetailPage,
} from "../features/insurance/policies/PolicyPages";
import { CaseListPage, CaseNewPage, CaseDetailPage } from "../features/insurance/cases/CasePages";
import { ClaimWorkbench } from "../features/insurance/claims/ClaimWorkbench";
import { ClaimNewPage, ClaimDetailPage } from "../features/insurance/claims/ClaimPages";
import {
  EventDetailPage,
  ExpenseNewPage,
  PayoutNewPage,
  PayoutListPage,
  ReturnNewPage,
} from "../features/insurance/events/EventPages";
import { AuditPage } from "../features/audit/AuditPage";
import { PeoplePage } from "../features/household/PeoplePage";
import { SettingsPage } from "../features/household/SettingsPage";
import { ExportsPage } from "../features/exports/ExportsPage";
import { VaultPage } from "../features/vault/VaultPage";
import { canGoBackWithinApp, registerAndroidBackHandler } from "../platform/navigation";
import { MonthProvider } from "../shared/MonthContext";
import { RelatedLinks } from "../shared/RelatedLinks";
import type { NavigationGroup, ScreenLink } from "../shared/screens";
import { useHistoryScroll } from "../shared/historyRestore";
import { UnsavedChangesProvider, useLeavePrompt } from "../shared/UnsavedChanges";

const screens = [
  {
    path: "/",
    title: "오늘의 살림",
    group: "home" as NavigationGroup,
    parent: { to: "/", label: "홈" },
    live: true,
    element: <Dashboard welcome={<SignedOutWelcome />} />,
  },
  {
    path: "/more",
    title: "더보기",
    group: "more" as NavigationGroup,
    parent: { to: "/", label: "홈" },
    live: true,
    element: (
      <>
        <div className="intro">
          <h1>더보기</h1>
          <p>우리 집 물건과 공동 가계의 설정을 관리해요.</p>
        </div>
        <RelatedLinks
          links={householdScreens.find((screen) => screen.path === "/more")!.links ?? []}
        />
      </>
    ),
  },
  {
    path: "/appliances",
    title: "가전 관리",
    group: "more" as NavigationGroup,
    parent: { to: "/more", label: "더보기" },
    live: true,
    element: <ApplianceListPage />,
  },
  {
    path: "/appliances/new",
    title: "가전 등록",
    group: "more" as NavigationGroup,
    parent: { to: "/appliances", label: "가전 목록" },
    live: true,
    element: <ApplianceNewPage />,
  },
  {
    path: "/appliances/:id",
    title: "가전 상세",
    group: "more" as NavigationGroup,
    parent: { to: "/appliances", label: "가전 목록" },
    live: true,
    element: <ApplianceDetailPage />,
  },
  {
    path: "/appliances/:id/edit",
    title: "가전 정보 수정",
    group: "more" as NavigationGroup,
    parent: { to: "/appliances", label: "가전 목록" },
    live: true,
    element: <ApplianceDetailPage edit />,
  },
  {
    path: "/purchase-plan",
    title: "공용 소모품 구매 계획",
    group: "more" as NavigationGroup,
    parent: { to: "/consumables", label: "공용 재고" },
    live: true,
    element: <PurchasePlanPage />,
  },
  {
    path: "/consumable-orders",
    title: "구매 예정·주문 목록",
    group: "more" as NavigationGroup,
    parent: { to: "/purchase-plan", label: "구매 계획" },
    live: true,
    element: <OrderListPage />,
  },
  {
    path: "/consumable-orders/new",
    title: "구매 예정 추가",
    group: "more" as NavigationGroup,
    parent: { to: "/purchase-plan", label: "구매 계획" },
    live: true,
    element: <OrderNewPage />,
  },
  {
    path: "/consumable-orders/:id",
    title: "소모품 주문 상세",
    group: "more" as NavigationGroup,
    parent: { to: "/consumable-orders", label: "구매·주문 목록" },
    live: true,
    element: <OrderDetailPage />,
  },
  {
    path: "/consumables",
    title: "소모품 관리",
    group: "more" as NavigationGroup,
    parent: { to: "/more", label: "더보기" },
    live: true,
    element: <ConsumableListPage />,
  },
  {
    path: "/consumables/new",
    title: "소모품 등록",
    group: "more" as NavigationGroup,
    parent: { to: "/consumables", label: "소모품 목록" },
    live: true,
    element: <ConsumableNewPage />,
  },
  {
    path: "/consumables/:id",
    title: "소모품 상세",
    group: "more" as NavigationGroup,
    parent: { to: "/consumables", label: "소모품 목록" },
    live: true,
    element: <ConsumableDetailPage />,
  },
  {
    path: "/consumables/:id/edit",
    title: "소모품 정보 수정",
    group: "more" as NavigationGroup,
    parent: { to: "/consumables", label: "소모품 목록" },
    live: true,
    element: <ConsumableDetailPage edit />,
  },
  {
    path: "/consumables/:id/stock/new",
    title: "입고·재고 조정",
    group: "more" as NavigationGroup,
    parent: { to: "/consumables", label: "공용 재고" },
    live: true,
    element: <StockNewPage />,
  },
  {
    path: "/consumables/:id/stock/:movementId",
    title: "재고 원본 상세",
    group: "more" as NavigationGroup,
    parent: { to: "/consumables", label: "공용 재고" },
    live: true,
    element: <StockDetailPage />,
  },
  {
    path: "/appliance-consumables/:id",
    title: "기기별 소모품 관리",
    group: "more" as NavigationGroup,
    parent: { to: "/consumables", label: "소모품 목록" },
    live: true,
    element: <DeviceDetailPage />,
  },
  {
    path: "/appliance-consumables/:id/replace",
    title: "소모품 교체 기록",
    group: "more" as NavigationGroup,
    parent: { to: "/consumables", label: "소모품 목록" },
    live: true,
    element: <DeviceDetailPage replacing />,
  },
  {
    path: "/appliance-consumables/:id/replacements/:replacementId",
    title: "교체 기록 상세",
    group: "more" as NavigationGroup,
    parent: { to: "/consumables", label: "소모품 목록" },
    live: true,
    element: <ReplacementDetailPage />,
  },
  {
    path: "/exports",
    title: "자료 내보내기",
    group: "more" as NavigationGroup,
    parent: { to: "/settings", label: "설정" },
    live: true,
    element: <ExportsPage />,
  },
  {
    path: "/vault",
    title: "보관함",
    group: "more" as NavigationGroup,
    parent: { to: "/more", label: "더보기" },
    live: true,
    element: <VaultPage />,
  },
  ...authScreens.map((screen) => ({
    ...screen,
    live: true,
    element: screen.path === "/login" ? <LoginPage /> : <OnboardingPage />,
  })),
  {
    path: "/onboarding/connect",
    title: "배우자 연결",
    group: "more" as NavigationGroup,
    parent: { to: "/login", label: "로그인" },
    live: true,
    element: <OnboardingPage connect />,
  },
  {
    path: "/onboarding/invitation",
    title: "기존 초대로 등록",
    group: "more" as NavigationGroup,
    parent: { to: "/onboarding", label: "공동 가계 시작" },
    live: true,
    element: <InvitationAcceptPage />,
  },
  {
    path: "/settings",
    title: "설정",
    group: "more" as NavigationGroup,
    parent: { to: "/more", label: "더보기" },
    live: true,
    element: <SettingsPage />,
  },
  {
    path: "/settings/people",
    title: "가족 관리",
    group: "more" as NavigationGroup,
    parent: { to: "/settings", label: "설정" },
    live: true,
    element: <PeoplePage />,
  },
  {
    path: "/activity",
    title: "최근 작업 이력",
    group: "more" as NavigationGroup,
    parent: { to: "/settings", label: "설정" },
    live: true,
    element: <ActivityPage />,
  },
  {
    path: "/settings/audit",
    title: "감사 이력",
    group: "more" as NavigationGroup,
    parent: { to: "/settings", label: "설정" },
    live: true,
    element: <AuditPage />,
  },
  {
    path: "/settings/auth",
    title: "계정과 기기",
    group: "more" as NavigationGroup,
    parent: { to: "/settings", label: "설정" },
    live: true,
    element: <SessionSettings />,
  },
  ...assetScreens
    .filter((screen) => screen.path === "/assets" || screen.path === "/assets/:id")
    .map((screen) => ({
      ...screen,
      live: true,
      element: screen.path === "/assets" ? <AssetListPage /> : <AssetDetailPage />,
    })),
  {
    path: "/assets/new",
    title: "자산·부채 등록",
    group: "assets" as NavigationGroup,
    parent: { to: "/assets", label: "자산 목록" },
    live: true,
    element: <AssetNewPage />,
  },
  {
    path: "/assets/:id/edit",
    title: "자산 정보 수정",
    group: "assets" as NavigationGroup,
    parent: { to: "/assets", label: "자산 목록" },
    live: true,
    element: <AssetDetailPage edit />,
  },
  ...accountScreens.map((screen) => ({
    ...screen,
    live: true,
    element: screen.path === "/accounts" ? <AccountListPage /> : <AccountDetailPage />,
  })),
  {
    path: "/accounts/new",
    title: "계좌 등록",
    group: "assets" as NavigationGroup,
    parent: { to: "/accounts", label: "계좌 목록" },
    live: true,
    element: <AccountNewPage />,
  },
  {
    path: "/accounts/:id/edit",
    title: "계좌 정보 수정",
    group: "assets" as NavigationGroup,
    parent: { to: "/accounts", label: "계좌 목록" },
    live: true,
    element: <AccountDetailPage edit />,
  },
  {
    path: "/assets/months/:month",
    title: "월별 자산 확인",
    group: "assets" as NavigationGroup,
    parent: { to: "/assets", label: "자산 목록" },
    live: true,
    element: <AssetMonthPage />,
  },
  {
    path: "/assets/compare",
    title: "월간 자산 비교",
    group: "assets" as NavigationGroup,
    parent: { to: "/assets", label: "자산 목록" },
    live: true,
    element: <AssetComparisonPage />,
  },
  {
    path: "/living",
    title: "생활비",
    group: "living" as NavigationGroup,
    parent: { to: "/", label: "홈" },
    live: true,
    element: <LivingPage />,
  },
  {
    path: "/income",
    title: "월간 수입",
    group: "living" as NavigationGroup,
    parent: { to: "/living", label: "생활비" },
    live: true,
    element: <IncomeListPage />,
  },
  {
    path: "/income/new",
    title: "수입 입력",
    group: "living" as NavigationGroup,
    parent: { to: "/income", label: "수입 목록" },
    live: true,
    element: <IncomeNewPage />,
  },
  {
    path: "/income/convert",
    title: "월합계·일별 수입 전환",
    group: "living" as NavigationGroup,
    parent: { to: "/income", label: "수입 목록" },
    live: true,
    element: <IncomeConversionPage />,
  },
  {
    path: "/income/:id",
    title: "수입 상세",
    group: "living" as NavigationGroup,
    parent: { to: "/income", label: "수입 목록" },
    live: true,
    element: <IncomeDetailPage />,
  },
  {
    path: "/income/:id/edit",
    title: "수입 정정",
    group: "living" as NavigationGroup,
    parent: { to: "/income", label: "수입 목록" },
    live: true,
    element: <IncomeDetailPage edit />,
  },
  {
    path: "/cards",
    title: "카드 관리",
    group: "living" as NavigationGroup,
    parent: { to: "/living", label: "생활비" },
    live: true,
    element: <CardListPage />,
  },
  {
    path: "/cards/new",
    title: "카드 등록",
    group: "living" as NavigationGroup,
    parent: { to: "/cards", label: "카드 목록" },
    live: true,
    element: <CardNewPage />,
  },
  {
    path: "/cards/:id",
    title: "카드 상세",
    group: "living" as NavigationGroup,
    parent: { to: "/cards", label: "카드 목록" },
    live: true,
    element: <CardDetailPage />,
  },
  {
    path: "/cards/:id/edit",
    title: "카드 정보 수정",
    group: "living" as NavigationGroup,
    parent: { to: "/cards", label: "카드 목록" },
    live: true,
    element: <CardDetailPage edit />,
  },
  {
    path: "/fixed-payments",
    title: "고정 납부",
    group: "living" as NavigationGroup,
    parent: { to: "/living", label: "생활비" },
    live: true,
    element: <FixedListPage />,
  },
  {
    path: "/fixed-payments/rules",
    title: "납부 규칙 관리",
    group: "living" as NavigationGroup,
    parent: { to: "/fixed-payments", label: "고정 납부" },
    live: true,
    element: <RuleListPage />,
  },
  {
    path: "/fixed-payments/rules/new",
    title: "납부 규칙 등록",
    group: "living" as NavigationGroup,
    parent: { to: "/fixed-payments/rules", label: "납부 규칙" },
    live: true,
    element: <RuleNewPage />,
  },
  {
    path: "/fixed-payments/rules/:id",
    title: "납부 규칙 상세",
    group: "living" as NavigationGroup,
    parent: { to: "/fixed-payments/rules", label: "납부 규칙" },
    live: true,
    element: <RuleDetailPage />,
  },
  {
    path: "/fixed-payments/rules/:id/edit",
    title: "납부 규칙 변경",
    group: "living" as NavigationGroup,
    parent: { to: "/fixed-payments/rules", label: "납부 규칙" },
    live: true,
    element: <RuleDetailPage edit />,
  },
  {
    path: "/fixed-payments/:id",
    title: "고정 납부 상세",
    group: "living" as NavigationGroup,
    parent: { to: "/fixed-payments", label: "고정 납부 목록" },
    live: true,
    element: <FixedDetailPage />,
  },
  {
    path: "/insurance",
    title: "보험",
    group: "insurance" as NavigationGroup,
    parent: { to: "/", label: "홈" },
    live: true,
    element: <InsuranceHome />,
  },
  {
    path: "/insurance/policies",
    title: "보험 계약",
    group: "insurance" as NavigationGroup,
    parent: { to: "/insurance", label: "보험" },
    live: true,
    element: <PolicyListPage />,
  },
  {
    path: "/insurance/policies/new",
    title: "보험 계약 등록",
    group: "insurance" as NavigationGroup,
    parent: { to: "/insurance/policies", label: "보험 계약" },
    live: true,
    element: <PolicyNewPage />,
  },
  {
    path: "/insurance/policies/:id",
    title: "보험 계약 상세",
    group: "insurance" as NavigationGroup,
    parent: { to: "/insurance/policies", label: "보험 계약" },
    live: true,
    element: <PolicyDetailPage />,
  },
  {
    path: "/insurance/policies/:id/edit",
    title: "보험 계약 수정",
    group: "insurance" as NavigationGroup,
    parent: { to: "/insurance/policies", label: "보험 계약" },
    live: true,
    element: <PolicyDetailPage edit />,
  },
  {
    path: "/insurance/cases",
    title: "보험 사건",
    group: "insurance" as NavigationGroup,
    parent: { to: "/insurance", label: "보험" },
    live: true,
    element: <CaseListPage />,
  },
  {
    path: "/insurance/cases/new",
    title: "보험 사건 등록",
    group: "insurance" as NavigationGroup,
    parent: { to: "/insurance/cases", label: "보험 사건" },
    live: true,
    element: <CaseNewPage />,
  },
  {
    path: "/insurance/cases/:id",
    title: "보험 사건 상세",
    group: "insurance" as NavigationGroup,
    parent: { to: "/insurance/cases", label: "보험 사건" },
    live: true,
    element: <CaseDetailPage />,
  },
  {
    path: "/insurance/cases/:id/edit",
    title: "보험 사건 변경",
    group: "insurance" as NavigationGroup,
    parent: { to: "/insurance/cases", label: "보험 사건" },
    live: true,
    element: <CaseDetailPage edit />,
  },
  {
    path: "/insurance/cases/:id/nodes/:nodeId",
    title: "진료·약국 상세",
    group: "insurance" as NavigationGroup,
    parent: { to: "/insurance/cases", label: "보험 사건" },
    live: true,
    element: <CaseDetailPage />,
  },
  {
    path: "/insurance/expenses/new",
    title: "의료비 기록",
    group: "insurance" as NavigationGroup,
    parent: { to: "/insurance/cases", label: "보험 사건" },
    live: true,
    element: <ExpenseNewPage />,
  },
  {
    path: "/insurance/expenses/:id",
    title: "의료비 상세",
    group: "insurance" as NavigationGroup,
    parent: { to: "/insurance/cases", label: "보험 사건" },
    live: true,
    element: <EventDetailPage kind="expense" />,
  },
  {
    path: "/insurance/expenses/:id/correct",
    title: "의료비 정정",
    group: "insurance" as NavigationGroup,
    parent: { to: "/insurance/cases", label: "보험 사건" },
    live: true,
    element: <EventDetailPage kind="expense" edit />,
  },
  {
    path: "/insurance/expenses/:id/refunds/new",
    title: "의료비 환불 기록",
    group: "insurance" as NavigationGroup,
    parent: { to: "/insurance/cases", label: "보험 사건" },
    live: true,
    element: <ReturnNewPage kind="refund" />,
  },
  {
    path: "/insurance/refunds/:id",
    title: "의료비 환불 상세",
    group: "insurance" as NavigationGroup,
    parent: { to: "/insurance/cases", label: "보험 사건" },
    live: true,
    element: <EventDetailPage kind="refund" />,
  },
  {
    path: "/insurance/refunds/:id/correct",
    title: "의료비 환불 정정",
    group: "insurance" as NavigationGroup,
    parent: { to: "/insurance/cases", label: "보험 사건" },
    live: true,
    element: <EventDetailPage kind="refund" edit />,
  },
  {
    path: "/insurance/payouts",
    title: "보험금 수령 원본",
    group: "insurance" as NavigationGroup,
    parent: { to: "/insurance/cases", label: "보험 사건" },
    live: true,
    element: <PayoutListPage />,
  },
  {
    path: "/insurance/payouts/new",
    title: "보험금 수령 입력",
    group: "insurance" as NavigationGroup,
    parent: { to: "/insurance/cases", label: "보험 사건" },
    live: true,
    element: <PayoutNewPage />,
  },
  {
    path: "/insurance/payouts/:id",
    title: "보험금 수령 상세",
    group: "insurance" as NavigationGroup,
    parent: { to: "/insurance/cases", label: "보험 사건" },
    live: true,
    element: <EventDetailPage kind="payout" />,
  },
  {
    path: "/insurance/payouts/:id/correct",
    title: "보험금 수령 정정",
    group: "insurance" as NavigationGroup,
    parent: { to: "/insurance/cases", label: "보험 사건" },
    live: true,
    element: <EventDetailPage kind="payout" edit />,
  },
  {
    path: "/insurance/payouts/:id/returns/new",
    title: "보험금 반환 기록",
    group: "insurance" as NavigationGroup,
    parent: { to: "/insurance/cases", label: "보험 사건" },
    live: true,
    element: <ReturnNewPage kind="return" />,
  },
  {
    path: "/insurance/returns/:id",
    title: "보험금 반환 상세",
    group: "insurance" as NavigationGroup,
    parent: { to: "/insurance/cases", label: "보험 사건" },
    live: true,
    element: <EventDetailPage kind="return" />,
  },
  {
    path: "/insurance/returns/:id/correct",
    title: "보험금 반환 정정",
    group: "insurance" as NavigationGroup,
    parent: { to: "/insurance/cases", label: "보험 사건" },
    live: true,
    element: <EventDetailPage kind="return" edit />,
  },
  {
    path: "/insurance/claims",
    title: "보험 청구 작업 목록",
    group: "insurance" as NavigationGroup,
    parent: { to: "/insurance", label: "보험" },
    live: true,
    element: <ClaimWorkbench />,
  },
  {
    path: "/insurance/claims/new",
    title: "보험 청구 기록",
    group: "insurance" as NavigationGroup,
    parent: { to: "/insurance/cases", label: "보험 사건" },
    live: true,
    element: <ClaimNewPage />,
  },
  {
    path: "/insurance/claims/:id",
    title: "보험 청구 상세",
    group: "insurance" as NavigationGroup,
    parent: { to: "/insurance/cases", label: "보험 사건" },
    live: true,
    element: <ClaimDetailPage />,
  },
  {
    path: "/insurance/claims/:id/edit",
    title: "보험 청구 정정",
    group: "insurance" as NavigationGroup,
    parent: { to: "/insurance/cases", label: "보험 사건" },
    live: true,
    element: <ClaimDetailPage edit />,
  },
];

const navigation: {
  group: NavigationGroup;
  to: string;
  label: string;
  icon: IconName;
  children?: ScreenLink[];
}[] = [
  { group: "home", to: "/", label: "홈", icon: "home" },
  {
    group: "assets",
    to: "/assets",
    label: "자산",
    icon: "assets",
    children: [
      { to: "/accounts", label: "계좌" },
      { to: "/assets/compare", label: "월간 비교" },
    ],
  },
  {
    group: "living",
    to: "/living",
    label: "생활비",
    icon: "cashflow",
    children: [
      { to: "/income", label: "수입" },
      { to: "/fixed-payments", label: "고정 납부" },
      { to: "/cards", label: "카드" },
    ],
  },
  {
    group: "insurance",
    to: "/insurance",
    label: "보험",
    icon: "insurance",
    children: [
      { to: "/insurance/policies", label: "계약" },
      { to: "/insurance/cases", label: "사건·청구·지급" },
      { to: "/insurance/claims", label: "청구 작업" },
    ],
  },
  {
    group: "more",
    to: "/more",
    label: "더보기",
    icon: "more",
    children: [
      { to: "/appliances", label: "가전" },
      { to: "/consumables", label: "소모품" },
      { to: "/purchase-plan", label: "소모품 구매 계획·주문" },
      { to: "/vault", label: "보관함" },
      { to: "/settings", label: "설정" },
    ],
  },
];

function Navigation({ active, desktop = false }: { active?: NavigationGroup; desktop?: boolean }) {
  const { pathname } = useLocation();
  // The section link is "the page" only on its own path; on a sub-page it marks the section.
  const current = (item: (typeof navigation)[number]) =>
    pathname === item.to
      ? ("page" as const)
      : active === item.group
        ? ("true" as const)
        : undefined;
  return (
    <nav
      className={desktop ? "sidebar-nav" : "mobile-tabs"}
      aria-label={desktop ? "전체 메뉴" : "주 메뉴"}
    >
      <ul>
        {navigation.map((item) => (
          <li key={item.group}>
            <Link to={item.to} className="nav-item" aria-current={current(item)}>
              <span className="nav-icon">
                <Icon name={item.icon} />
              </span>
              <span>{item.label}</span>
            </Link>
            {desktop && item.children && (
              <ul className="subnav">
                {item.children.map((child) => (
                  <li key={child.to}>
                    <NavLink to={child.to}>{child.label}</NavLink>
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ul>
    </nav>
  );
}

function NotFound() {
  return (
    <>
      <div className="intro">
        <p className="eyebrow">페이지 안내</p>
        <h1>페이지를 찾을 수 없어요</h1>
        <p>주소를 확인하거나 홈에서 원하는 메뉴를 선택해 주세요.</p>
      </div>
      <Link className="button-link" to="/">
        홈으로 이동
      </Link>
    </>
  );
}

function AppShell() {
  return (
    <UnsavedChangesProvider>
      <ShellFrame />
    </UnsavedChangesProvider>
  );
}

function ShellFrame() {
  const leave = useLeavePrompt();
  const { state } = useAuth();
  const location = useLocation();
  const navigationType = useNavigationType();
  const navigate = useNavigate();
  const mainRef = useRef<HTMLElement>(null);
  const previousPath = useRef(location.pathname);
  const current = matchRoutes(screens, location)?.at(-1)?.route;
  const screen = current?.path;
  const previousScreen = useRef(screen);
  const parent = current?.parent.to ?? "/";
  const title = current?.title ?? "페이지를 찾을 수 없어요";
  const authPage = location.pathname === "/login" || location.pathname.startsWith("/onboarding");
  const domain =
    /^\/(appliances|consumables|appliance-consumables|consumable-orders|purchase-plan)/.test(
      location.pathname,
    )
      ? "homecare"
      : location.pathname.startsWith("/insurance") || location.pathname.includes("audit")
        ? "records"
        : "finance";

  function goBack() {
    if (canGoBackWithinApp(window.history.state)) navigate(-1);
    else navigate(parent, { replace: true });
  }

  useEffect(() => {
    document.title = location.pathname === "/" ? "SallimBook · 살림북" : `${title} · SallimBook`;
    const active = document.activeElement;
    const lost = !active || active === document.body;
    // A POP keeps its restored scroll and only recovers focus the old screen took with it.
    // A replace within the same screen (stepping the month) keeps the control the person used.
    const stays =
      navigationType === "POP" ||
      (navigationType === "REPLACE" && previousScreen.current === screen);
    if (previousPath.current !== location.pathname && (!stays || lost))
      mainRef.current?.focus({ preventScroll: true });
    previousPath.current = location.pathname;
    previousScreen.current = screen;
  }, [location.pathname, navigationType, title, screen]);
  useHistoryScroll(location, navigationType);

  const backState = useRef({ navigate, pathname: location.pathname, parent, leave });
  useLayoutEffect(() => {
    backState.current = { navigate, pathname: location.pathname, parent, leave };
  }, [navigate, location.pathname, parent, leave]);
  // Keep one native subscription while routing and dialog state change.
  useEffect(
    () =>
      registerAndroidBackHandler(() => {
        const { navigate, pathname, parent, leave } = backState.current;
        // A second back press while the leave prompt is open keeps the person editing.
        if (leave.open) {
          leave.stay();
          return true;
        }
        const filter = document.querySelector<HTMLDialogElement>(
          "dialog[data-filter-dialog][open]",
        );
        if (filter) {
          filter.close();
          return true;
        }
        if (canGoBackWithinApp(window.history.state)) {
          navigate(-1);
          return true;
        }
        if (pathname !== "/") {
          navigate(parent, { replace: true });
          return true;
        }
        return false;
      }),
    [],
  );

  return (
    <div className={`app-shell${authPage ? " auth-shell" : ""}`} data-domain={domain}>
      <a className="skip-link" href="#main-content">
        본문으로 바로가기
      </a>
      <aside className="sidebar">
        <Link className="brand" to="/" aria-label="SallimBook 홈">
          <span className="brand-mark">
            <Icon name="book" size={25} />
          </span>
          <span className="brand-name">
            SallimBook<small>살림북</small>
          </span>
        </Link>
        <p className="sidebar-caption">우리 가계</p>
        <Navigation desktop active={current?.group} />
        <div className="sidebar-footer">
          <Link
            className="sidebar-account"
            to={state.status === "authenticated" ? "/settings/auth" : "/login"}
          >
            <span className="account-avatar">
              <Icon name="account" size={18} />
            </span>
            <span>
              <strong>
                {state.status === "authenticated" ? state.member.display_name : "내 계정 연결"}
              </strong>
              <small>
                {state.status === "authenticated"
                  ? "함께 쓰는 공동 가계"
                  : "우리 집의 기록을 시작해요"}
              </small>
            </span>
            <Icon name="arrow-right" size={16} />
          </Link>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <Link className="brand" to="/" aria-label="SallimBook 홈">
            <span className="brand-mark">
              <Icon name="book" size={25} />
            </span>
            <span className="brand-name">
              SallimBook<small>살림북</small>
            </span>
          </Link>
          <div className="topbar-context">
            <span>우리 가계</span>
            <span aria-hidden="true">/</span>
            <strong>{title}</strong>
          </div>
          <Link className="topbar-link" to="/settings" aria-label="설정">
            <Icon name="settings" size={19} />
            <span>설정</span>
          </Link>
          {isNativeAuth() && (
            <button type="button" onClick={() => void nativeAuth.lock().catch(() => {})}>
              앱 잠금
            </button>
          )}
        </header>
        <div className="page">
          {location.pathname !== "/" && (
            <div className="back-row">
              <button className="back-button" onClick={goBack}>
                <Icon name="arrow-left" size={17} />
                뒤로
              </button>
              <span className="muted">{current?.parent.label ?? "홈"}</span>
            </div>
          )}
          <main id="main-content" ref={mainRef} tabIndex={-1}>
            <Routes>
              {screens.map((screen) => (
                <Route key={screen.path} path={screen.path} element={screen.element} />
              ))}
              <Route path="*" element={<NotFound />} />
            </Routes>
          </main>
          <footer>살림북 · 함께 쌓아가는 우리 집의 기록</footer>
        </div>
      </div>
      <Navigation active={current?.group} />
      <SessionExpiredDialog />
    </div>
  );
}

export function App() {
  return (
    <AuthProvider>
      <MonthProvider>
        <RecordActorsProvider>
          <AppShell />
        </RecordActorsProvider>
      </MonthProvider>
    </AuthProvider>
  );
}

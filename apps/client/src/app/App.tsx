import { useEffect, useRef } from "react";
import { isNativeAuth, nativeAuth } from "../platform/nativeAuth";
import { Link, matchRoutes, NavLink, Route, Routes, useLocation, useNavigate } from "react-router";
import { AccountListPage, AccountNewPage, AccountDetailPage } from "../features/accounts/AccountPages";
import { accountScreens } from "../features/accounts/screens";
import { assetScreens } from "../features/assets/screens";
import { AssetComparisonPage } from "../features/assets/comparison/ComparisonPage";
import { AssetMonthPage } from "../features/assets/months/MonthPage";
import { AssetListPage, AssetNewPage, AssetDetailPage } from "../features/assets/AssetPages";
import { authScreens } from "../features/auth/screens";
import { AuthProvider } from "../features/auth/AuthProvider";
import { InvitationAcceptPage } from "../features/auth/InvitationAcceptPage";
import { LoginPage } from "../features/auth/LoginPage";
import { SessionSettings } from "../features/auth/SessionSettings";
import { CardListPage, CardNewPage, CardDetailPage } from "../features/cards/CardPages";
import { IncomeListPage, IncomeNewPage, IncomeDetailPage } from "../features/income/IncomePages";
import { IncomeConversionPage } from "../features/income/IncomeConversion";
import { FixedListPage, FixedDetailPage, RuleListPage, RuleNewPage, RuleDetailPage } from "../features/fixed/FixedPages";
import { LivingPage } from "../features/living/LivingPage";
import { ApplianceListPage, ApplianceNewPage, ApplianceDetailPage } from "../features/homecare/AppliancePages";
import { ConsumableListPage, ConsumableNewPage, ConsumableDetailPage } from "../features/homecare/ConsumablePages";
import { DeviceDetailPage } from "../features/homecare/DeviceLinks";
import { StockNewPage, StockDetailPage } from "../features/homecare/StockPages";
import { ReplacementDetailPage } from "../features/homecare/ReplacementPages";
import { Dashboard } from "../features/dashboard/Dashboard";
import { householdScreens } from "../features/household/screens";
import { InsuranceHome } from "../features/insurance/InsuranceHome";
import { PolicyListPage, PolicyNewPage, PolicyDetailPage } from "../features/insurance/policies/PolicyPages";
import { CaseListPage, CaseNewPage, CaseDetailPage } from "../features/insurance/cases/CasePages";
import { ClaimNewPage, ClaimDetailPage } from "../features/insurance/claims/ClaimPages";
import { EventDetailPage, ExpenseNewPage, PayoutNewPage, PayoutListPage, ReturnNewPage } from "../features/insurance/events/EventPages";
import { VaultPage } from "../features/vault/VaultPage";
import { canGoBackWithinApp, registerAndroidBackHandler } from "../platform/navigation";
import { MonthProvider } from "../shared/MonthContext";
import { PlannedPage, RelatedLinks } from "../shared/PlannedPage";
import type { NavigationGroup, ScreenLink } from "../shared/screens";

const plannedScreens = [...assetScreens.filter((screen) => screen.path !== "/assets" && screen.path !== "/assets/:id" && screen.path !== "/assets/months/:month" && screen.path !== "/assets/compare"), ...householdScreens.filter((screen) => screen.path !== "/more" && !screen.path.startsWith("/appliances") && !screen.path.startsWith("/consumables"))];
const screens = [
  { path: "/", title: "함께 살피는 오늘의 살림", group: "home" as NavigationGroup, parent: { to: "/", label: "홈" }, live: true, element: <Dashboard /> },
  { path: "/more", title: "더보기", group: "more" as NavigationGroup, parent: { to: "/", label: "홈" }, live: true, element: <><div className="intro"><h1>더보기</h1><p>우리 집 물건과 공동 가계의 설정을 관리해요.</p></div><RelatedLinks links={householdScreens.find((screen) => screen.path === "/more")!.links ?? []} /></> },
  { path: "/appliances", title: "가전 관리", group: "more" as NavigationGroup, parent: { to: "/more", label: "더보기" }, live: true, element: <ApplianceListPage /> },
  { path: "/appliances/new", title: "가전 등록", group: "more" as NavigationGroup, parent: { to: "/appliances", label: "가전 목록" }, live: true, element: <ApplianceNewPage /> },
  { path: "/appliances/:id", title: "가전 상세", group: "more" as NavigationGroup, parent: { to: "/appliances", label: "가전 목록" }, live: true, element: <ApplianceDetailPage /> },
  { path: "/appliances/:id/edit", title: "가전 정보 수정", group: "more" as NavigationGroup, parent: { to: "/appliances", label: "가전 목록" }, live: true, element: <ApplianceDetailPage edit /> },
  { path: "/consumables", title: "소모품 관리", group: "more" as NavigationGroup, parent: { to: "/more", label: "더보기" }, live: true, element: <ConsumableListPage /> },
  { path: "/consumables/new", title: "소모품 등록", group: "more" as NavigationGroup, parent: { to: "/consumables", label: "소모품 목록" }, live: true, element: <ConsumableNewPage /> },
  { path: "/consumables/:id", title: "소모품 상세", group: "more" as NavigationGroup, parent: { to: "/consumables", label: "소모품 목록" }, live: true, element: <ConsumableDetailPage /> },
  { path: "/consumables/:id/edit", title: "소모품 정보 수정", group: "more" as NavigationGroup, parent: { to: "/consumables", label: "소모품 목록" }, live: true, element: <ConsumableDetailPage edit /> },
  { path: "/consumables/:id/stock/new", title: "입고·재고 조정", group: "more" as NavigationGroup, parent: { to: "/consumables", label: "공용 재고" }, live: true, element: <StockNewPage /> },
  { path: "/consumables/:id/stock/:movementId", title: "재고 원본 상세", group: "more" as NavigationGroup, parent: { to: "/consumables", label: "공용 재고" }, live: true, element: <StockDetailPage /> },
  { path: "/appliance-consumables/:id", title: "기기별 소모품 관리", group: "more" as NavigationGroup, parent: { to: "/consumables", label: "소모품 목록" }, live: true, element: <DeviceDetailPage /> },
  { path: "/appliance-consumables/:id/replace", title: "소모품 교체 기록", group: "more" as NavigationGroup, parent: { to: "/consumables", label: "소모품 목록" }, live: true, element: <DeviceDetailPage replacing /> },
  { path: "/appliance-consumables/:id/replacements/:replacementId", title: "교체 기록 상세", group: "more" as NavigationGroup, parent: { to: "/consumables", label: "소모품 목록" }, live: true, element: <ReplacementDetailPage /> },
  { path: "/vault", title: "보관함", group: "more" as NavigationGroup, parent: { to: "/more", label: "더보기" }, live: false, element: <VaultPage /> },
  ...authScreens.map((screen) => ({ ...screen, live: true, element: screen.path === "/login" ? <LoginPage /> : <InvitationAcceptPage /> })),
  { path: "/settings/auth", title: "계정과 기기", group: "more" as NavigationGroup, parent: { to: "/settings", label: "설정" }, live: true, element: <SessionSettings /> },
  ...assetScreens.filter((screen) => screen.path === "/assets" || screen.path === "/assets/:id").map((screen) => ({ ...screen, live: true, element: screen.path === "/assets" ? <AssetListPage /> : <AssetDetailPage /> })),
  { path: "/assets/new", title: "자산·부채 등록", group: "assets" as NavigationGroup, parent: { to: "/assets", label: "자산 목록" }, live: true, element: <AssetNewPage /> },
  { path: "/assets/:id/edit", title: "자산 정보 수정", group: "assets" as NavigationGroup, parent: { to: "/assets", label: "자산 목록" }, live: true, element: <AssetDetailPage edit /> },
  ...accountScreens.map((screen) => ({ ...screen, live: true, element: screen.path === "/accounts" ? <AccountListPage /> : <AccountDetailPage /> })),
  { path: "/accounts/new", title: "계좌 등록", group: "assets" as NavigationGroup, parent: { to: "/accounts", label: "계좌 목록" }, live: true, element: <AccountNewPage /> },
  { path: "/accounts/:id/edit", title: "계좌 정보 수정", group: "assets" as NavigationGroup, parent: { to: "/accounts", label: "계좌 목록" }, live: true, element: <AccountDetailPage edit /> },
  { path: "/assets/months/:month", title: "월별 자산 확인", group: "assets" as NavigationGroup, parent: { to: "/assets", label: "자산 목록" }, live: true, element: <AssetMonthPage /> },
  { path: "/assets/compare", title: "월간 자산 비교", group: "assets" as NavigationGroup, parent: { to: "/assets", label: "자산 목록" }, live: true, element: <AssetComparisonPage /> },
  { path: "/living", title: "생활비", group: "living" as NavigationGroup, parent: { to: "/", label: "홈" }, live: true, element: <LivingPage /> },
  { path: "/income", title: "월간 수입", group: "living" as NavigationGroup, parent: { to: "/living", label: "생활비" }, live: true, element: <IncomeListPage /> },
  { path: "/income/new", title: "수입 입력", group: "living" as NavigationGroup, parent: { to: "/income", label: "수입 목록" }, live: true, element: <IncomeNewPage /> },
  { path: "/income/convert", title: "월합계·일별 수입 전환", group: "living" as NavigationGroup, parent: { to: "/income", label: "수입 목록" }, live: true, element: <IncomeConversionPage /> },
  { path: "/income/:id", title: "수입 상세", group: "living" as NavigationGroup, parent: { to: "/income", label: "수입 목록" }, live: true, element: <IncomeDetailPage /> },
  { path: "/income/:id/edit", title: "수입 정정", group: "living" as NavigationGroup, parent: { to: "/income", label: "수입 목록" }, live: true, element: <IncomeDetailPage edit /> },
  { path: "/cards", title: "카드 관리", group: "living" as NavigationGroup, parent: { to: "/living", label: "생활비" }, live: true, element: <CardListPage /> },
  { path: "/cards/new", title: "카드 등록", group: "living" as NavigationGroup, parent: { to: "/cards", label: "카드 목록" }, live: true, element: <CardNewPage /> },
  { path: "/cards/:id", title: "카드 상세", group: "living" as NavigationGroup, parent: { to: "/cards", label: "카드 목록" }, live: true, element: <CardDetailPage /> },
  { path: "/cards/:id/edit", title: "카드 정보 수정", group: "living" as NavigationGroup, parent: { to: "/cards", label: "카드 목록" }, live: true, element: <CardDetailPage edit /> },
  { path: "/fixed-payments", title: "고정 납부", group: "living" as NavigationGroup, parent: { to: "/living", label: "생활비" }, live: true, element: <FixedListPage /> },
  { path: "/fixed-payments/rules", title: "납부 규칙 관리", group: "living" as NavigationGroup, parent: { to: "/fixed-payments", label: "고정 납부" }, live: true, element: <RuleListPage /> },
  { path: "/fixed-payments/rules/new", title: "납부 규칙 등록", group: "living" as NavigationGroup, parent: { to: "/fixed-payments/rules", label: "납부 규칙" }, live: true, element: <RuleNewPage /> },
  { path: "/fixed-payments/rules/:id", title: "납부 규칙 상세", group: "living" as NavigationGroup, parent: { to: "/fixed-payments/rules", label: "납부 규칙" }, live: true, element: <RuleDetailPage /> },
  { path: "/fixed-payments/rules/:id/edit", title: "납부 규칙 변경", group: "living" as NavigationGroup, parent: { to: "/fixed-payments/rules", label: "납부 규칙" }, live: true, element: <RuleDetailPage edit /> },
  { path: "/fixed-payments/:id", title: "고정 납부 상세", group: "living" as NavigationGroup, parent: { to: "/fixed-payments", label: "고정 납부 목록" }, live: true, element: <FixedDetailPage /> },
  { path: "/insurance", title: "보험", group: "insurance" as NavigationGroup, parent: { to: "/", label: "홈" }, live: true, element: <InsuranceHome /> },
  { path: "/insurance/policies", title: "보험 계약", group: "insurance" as NavigationGroup, parent: { to: "/insurance", label: "보험" }, live: true, element: <PolicyListPage /> },
  { path: "/insurance/policies/new", title: "보험 계약 등록", group: "insurance" as NavigationGroup, parent: { to: "/insurance/policies", label: "보험 계약" }, live: true, element: <PolicyNewPage /> },
  { path: "/insurance/policies/:id", title: "보험 계약 상세", group: "insurance" as NavigationGroup, parent: { to: "/insurance/policies", label: "보험 계약" }, live: true, element: <PolicyDetailPage /> },
  { path: "/insurance/policies/:id/edit", title: "보험 계약 수정", group: "insurance" as NavigationGroup, parent: { to: "/insurance/policies", label: "보험 계약" }, live: true, element: <PolicyDetailPage edit /> },
  { path: "/insurance/cases", title: "보험 사건", group: "insurance" as NavigationGroup, parent: { to: "/insurance", label: "보험" }, live: true, element: <CaseListPage /> },
  { path: "/insurance/cases/new", title: "보험 사건 등록", group: "insurance" as NavigationGroup, parent: { to: "/insurance/cases", label: "보험 사건" }, live: true, element: <CaseNewPage /> },
  { path: "/insurance/cases/:id", title: "보험 사건 상세", group: "insurance" as NavigationGroup, parent: { to: "/insurance/cases", label: "보험 사건" }, live: true, element: <CaseDetailPage /> },
  { path: "/insurance/cases/:id/edit", title: "보험 사건 변경", group: "insurance" as NavigationGroup, parent: { to: "/insurance/cases", label: "보험 사건" }, live: true, element: <CaseDetailPage edit /> },
  { path: "/insurance/cases/:id/nodes/:nodeId", title: "진료·약국 상세", group: "insurance" as NavigationGroup, parent: { to: "/insurance/cases", label: "보험 사건" }, live: true, element: <CaseDetailPage /> },
  { path: "/insurance/expenses/new", title: "의료비 기록", group: "insurance" as NavigationGroup, parent: { to: "/insurance/cases", label: "보험 사건" }, live: true, element: <ExpenseNewPage /> },
  { path: "/insurance/expenses/:id", title: "의료비 상세", group: "insurance" as NavigationGroup, parent: { to: "/insurance/cases", label: "보험 사건" }, live: true, element: <EventDetailPage kind="expense" /> },
  { path: "/insurance/expenses/:id/correct", title: "의료비 정정", group: "insurance" as NavigationGroup, parent: { to: "/insurance/cases", label: "보험 사건" }, live: true, element: <EventDetailPage kind="expense" edit /> },
  { path: "/insurance/expenses/:id/refunds/new", title: "의료비 환불 기록", group: "insurance" as NavigationGroup, parent: { to: "/insurance/cases", label: "보험 사건" }, live: true, element: <ReturnNewPage kind="refund" /> },
  { path: "/insurance/refunds/:id", title: "의료비 환불 상세", group: "insurance" as NavigationGroup, parent: { to: "/insurance/cases", label: "보험 사건" }, live: true, element: <EventDetailPage kind="refund" /> },
  { path: "/insurance/refunds/:id/correct", title: "의료비 환불 정정", group: "insurance" as NavigationGroup, parent: { to: "/insurance/cases", label: "보험 사건" }, live: true, element: <EventDetailPage kind="refund" edit /> },
  { path: "/insurance/payouts", title: "보험금 수령 원본", group: "insurance" as NavigationGroup, parent: { to: "/insurance/cases", label: "보험 사건" }, live: true, element: <PayoutListPage /> },
  { path: "/insurance/payouts/new", title: "보험금 수령 입력", group: "insurance" as NavigationGroup, parent: { to: "/insurance/cases", label: "보험 사건" }, live: true, element: <PayoutNewPage /> },
  { path: "/insurance/payouts/:id", title: "보험금 수령 상세", group: "insurance" as NavigationGroup, parent: { to: "/insurance/cases", label: "보험 사건" }, live: true, element: <EventDetailPage kind="payout" /> },
  { path: "/insurance/payouts/:id/correct", title: "보험금 수령 정정", group: "insurance" as NavigationGroup, parent: { to: "/insurance/cases", label: "보험 사건" }, live: true, element: <EventDetailPage kind="payout" edit /> },
  { path: "/insurance/payouts/:id/returns/new", title: "보험금 반환 기록", group: "insurance" as NavigationGroup, parent: { to: "/insurance/cases", label: "보험 사건" }, live: true, element: <ReturnNewPage kind="return" /> },
  { path: "/insurance/returns/:id", title: "보험금 반환 상세", group: "insurance" as NavigationGroup, parent: { to: "/insurance/cases", label: "보험 사건" }, live: true, element: <EventDetailPage kind="return" /> },
  { path: "/insurance/returns/:id/correct", title: "보험금 반환 정정", group: "insurance" as NavigationGroup, parent: { to: "/insurance/cases", label: "보험 사건" }, live: true, element: <EventDetailPage kind="return" edit /> },
  { path: "/insurance/claims/new", title: "보험 청구 기록", group: "insurance" as NavigationGroup, parent: { to: "/insurance/cases", label: "보험 사건" }, live: true, element: <ClaimNewPage /> },
  { path: "/insurance/claims/:id", title: "보험 청구 상세", group: "insurance" as NavigationGroup, parent: { to: "/insurance/cases", label: "보험 사건" }, live: true, element: <ClaimDetailPage /> },
  { path: "/insurance/claims/:id/edit", title: "보험 청구 정정", group: "insurance" as NavigationGroup, parent: { to: "/insurance/cases", label: "보험 사건" }, live: true, element: <ClaimDetailPage edit /> },
  ...plannedScreens.map((screen) => ({ ...screen, live: false, element: <PlannedPage screen={screen} /> })),
];

const navigation: { group: NavigationGroup; to: string; label: string; icon: string; children?: ScreenLink[] }[] = [
  { group: "home", to: "/", label: "홈", icon: "⌂" },
  { group: "assets", to: "/assets", label: "자산", icon: "▥", children: [{ to: "/accounts", label: "계좌" }, { to: "/assets/compare", label: "월간 비교" }] },
  { group: "living", to: "/living", label: "생활비", icon: "↔", children: [{ to: "/income", label: "수입" }, { to: "/fixed-payments", label: "고정 납부" }, { to: "/cards", label: "카드" }] },
  { group: "insurance", to: "/insurance", label: "보험", icon: "♡", children: [{ to: "/insurance/policies", label: "계약" }, { to: "/insurance/cases", label: "사건·청구·지급" }] },
  { group: "more", to: "/more", label: "더보기", icon: "···", children: [{ to: "/appliances", label: "가전" }, { to: "/consumables", label: "소모품" }, { to: "/vault", label: "보관함" }, { to: "/settings", label: "설정" }] },
];

function Navigation({ active, desktop = false }: { active?: NavigationGroup; desktop?: boolean }) {
  return (
    <nav className={desktop ? "sidebar-nav" : "mobile-tabs"} aria-label={desktop ? "전체 메뉴" : "주 메뉴"}>
      <ul>{navigation.map((item) => <li key={item.group}>
        <Link to={item.to} className="nav-item" aria-current={active === item.group ? "page" : undefined}>
          <span className="nav-icon" aria-hidden="true">{item.icon}</span><span>{item.label}</span>
        </Link>
        {desktop && item.children && <ul className="subnav">{item.children.map((child) => <li key={child.to}><NavLink to={child.to}>{child.label}</NavLink></li>)}</ul>}
      </li>)}</ul>
    </nav>
  );
}

function NotFound() {
  return <><div className="intro"><p className="eyebrow">페이지 안내</p><h1>페이지를 찾을 수 없어요</h1><p>주소를 확인하거나 홈에서 원하는 메뉴를 선택해 주세요.</p></div><Link className="button-link" to="/">홈으로 이동</Link></>;
}

function AppShell() {
  const location = useLocation();
  const navigate = useNavigate();
  const mainRef = useRef<HTMLElement>(null);
  const previousPath = useRef(location.pathname);
  const current = matchRoutes(screens, location)?.at(-1)?.route;
  const parent = current?.parent.to ?? "/";
  const title = current?.title ?? "페이지를 찾을 수 없어요";

  function goBack() {
    if (canGoBackWithinApp(window.history.state)) navigate(-1);
    else navigate(parent, { replace: true });
  }

  useEffect(() => {
    document.title = location.pathname === "/" ? "SallimBook · 살림북" : `${title} · SallimBook`;
    if (previousPath.current !== location.pathname) {
      mainRef.current?.focus();
      window.scrollTo(0, 0);
    }
    previousPath.current = location.pathname;
  }, [location.pathname, title]);

  useEffect(() => registerAndroidBackHandler(() => {
    if (canGoBackWithinApp(window.history.state)) {
      navigate(-1);
      return true;
    }
    if (location.pathname !== "/") {
      navigate(parent, { replace: true });
      return true;
    }
    return false;
  }), [navigate, location.pathname, parent]);

  return (
    <>
      <a className="skip-link" href="#main-content">본문으로 바로가기</a>
      <aside className="sidebar">
        <Link className="brand" to="/" aria-label="SallimBook 홈"><span className="brand-mark" aria-hidden="true">살림</span><span>SallimBook</span></Link>
        <p className="sidebar-caption">함께 쌓는 우리 집의 기록</p>
        <Navigation desktop active={current?.group} />
      </aside>
      <div className="workspace">
        <header className="topbar">
          <Link className="brand" to="/" aria-label="SallimBook 홈"><span className="brand-mark" aria-hidden="true">살림</span><span>SallimBook</span></Link>
          <Link className="topbar-link" to="/settings">설정</Link>
          {isNativeAuth() && <button type="button" onClick={() => void nativeAuth.lock().catch(() => {})}>앱 잠금</button>}
        </header>
        <div className="page">
          {!current?.live && <p className="preview-notice">기능 준비 중 · 현재는 화면 탐색만 가능해요.</p>}
          {location.pathname !== "/" && <div className="back-row"><button className="back-button" onClick={goBack}><span aria-hidden="true">← </span>뒤로</button><span className="muted">{current?.parent.label ?? "홈"}</span></div>}
          <main id="main-content" ref={mainRef} tabIndex={-1}>
            <Routes>{screens.map((screen) => <Route key={screen.path} path={screen.path} element={screen.element} />)}<Route path="*" element={<NotFound />} /></Routes>
          </main>
          <footer>살림북 · 함께 쌓아가는 우리 집의 기록</footer>
        </div>
      </div>
      <Navigation active={current?.group} />
    </>
  );
}

export function App() { return <AuthProvider><MonthProvider><AppShell /></MonthProvider></AuthProvider>; }

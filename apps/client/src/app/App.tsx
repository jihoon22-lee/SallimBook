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
import { Dashboard } from "../features/dashboard/Dashboard";
import { householdScreens } from "../features/household/screens";
import { insuranceScreens } from "../features/insurance/screens";
import { VaultPage } from "../features/vault/VaultPage";
import { canGoBackWithinApp, registerAndroidBackHandler } from "../platform/navigation";
import { MonthProvider } from "../shared/MonthContext";
import { PlannedPage } from "../shared/PlannedPage";
import type { NavigationGroup, ScreenLink } from "../shared/screens";

const plannedScreens = [...assetScreens.filter((screen) => screen.path !== "/assets" && screen.path !== "/assets/:id" && screen.path !== "/assets/months/:month" && screen.path !== "/assets/compare"), ...householdScreens, ...insuranceScreens];
const screens = [
  { path: "/", title: "함께 살피는 오늘의 살림", group: "home" as NavigationGroup, parent: { to: "/", label: "홈" }, live: true, element: <Dashboard /> },
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

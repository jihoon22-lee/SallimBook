import { useEffect, useRef } from "react";
import { Link, matchRoutes, NavLink, Route, Routes, useLocation, useNavigate } from "react-router";
import { accountScreens } from "../features/accounts/screens";
import { assetScreens } from "../features/assets/screens";
import { authScreens } from "../features/auth/screens";
import { AuthProvider } from "../features/auth/AuthProvider";
import { InvitationAcceptPage } from "../features/auth/InvitationAcceptPage";
import { LoginPage } from "../features/auth/LoginPage";
import { SessionSettings } from "../features/auth/SessionSettings";
import { cardScreens } from "../features/cards/screens";
import { Dashboard } from "../features/dashboard/Dashboard";
import { householdScreens } from "../features/household/screens";
import { insuranceScreens } from "../features/insurance/screens";
import { livingScreens } from "../features/living/screens";
import { VaultPage } from "../features/vault/VaultPage";
import { canGoBackWithinApp, registerAndroidBackHandler } from "../platform/navigation";
import { MonthProvider } from "../shared/MonthContext";
import { PlannedPage } from "../shared/PlannedPage";
import type { NavigationGroup, ScreenLink } from "../shared/screens";

const plannedScreens = [...assetScreens, ...accountScreens, ...cardScreens, ...householdScreens, ...insuranceScreens, ...livingScreens];
const screens = [
  { path: "/", title: "함께 살피는 오늘의 살림", group: "home" as NavigationGroup, parent: { to: "/", label: "홈" }, element: <Dashboard /> },
  { path: "/vault", title: "보관함", group: "more" as NavigationGroup, parent: { to: "/more", label: "더보기" }, element: <VaultPage /> },
  ...authScreens.map((screen) => ({ ...screen, element: screen.path === "/login" ? <LoginPage /> : <InvitationAcceptPage /> })),
  { path: "/settings/auth", title: "계정과 기기", group: "more" as NavigationGroup, parent: { to: "/settings", label: "설정" }, element: <SessionSettings /> },
  ...plannedScreens.map((screen) => ({ ...screen, element: <PlannedPage screen={screen} /> })),
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
        </header>
        <div className="page">
          {!["/login", "/onboarding", "/settings/auth"].includes(location.pathname) && <p className="preview-notice">기능 준비 중 · 현재는 화면 탐색만 가능해요.</p>}
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

# ADR 0001 — 공통 React UI + Android 네이티브 경계

상태: 설계 채택 · 날짜: 2026-10-17 · 구현 검증 전

## 배경

대부분 Android에서 사용하지만 PC 웹에서도 같은 기록을 관리해야 한다. 카드 비밀은 기기 보안 기능이 중요하다.

## 결정

React/TypeScript/Vite를 공유하고 Android는 Capacitor와 작은 Kotlin 보안 모듈을 사용한다. 보안 비밀 UI는 네이티브로 격리한다.

## 결과와 비용

Android·웹을 별도 제품으로 만드는 비용을 줄인다. 대신 WebView/bridge 신뢰 경계와 양 플랫폼 회귀시험이 필요하다. Flutter/Kotlin 전면 재작성은 현재 범위에 넣지 않는다.

## 검증

관련 요구사항의 인수 기준과 보안 게이트를 따른다. 결정 변경은 새 ADR로 기록하고 기존 문서를 무단 삭제하지 않는다.

[아키텍처](../architecture.md) · [제품 요구사항](../product-requirements.md) · [보안 정책](../security-authentication.md)

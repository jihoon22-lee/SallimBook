// Test-APK-only predicate for a newly created household with no domain records.
// Headings alone also render before authentication. Require both API-backed panels.
(() => {
  const main = document.querySelector('#main-content');
  const assets = main?.querySelector('section[aria-label="저장된 자산 금액"]');
  const care = main?.querySelector('section[aria-labelledby="consumables-title"]');
  if (location.pathname !== '/' || !assets || !care) return false;
  if (assets.querySelector('[role="alert"]') || care.querySelector('[role="alert"]')) return false;
  if (main.querySelector('a[href="/login"]')) return false;
  // The household status loaded: a new household has nothing to total yet.
  const emptyHoldings = assets.textContent.includes('아직 합계에 넣을 자산·계좌가 없어요.');
  const loadedInventory = care.querySelector('select') !== null &&
    care.textContent.includes('사용 중인 가전과 소모품 연결이 없어요.');
  return emptyHoldings && loadedInventory;
})();

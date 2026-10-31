// Test-APK-only booleans. Never return DOM text, HTML, values, URLs or API data.
// route, main, assets, care, login link, asset alert, care alert,
// empty month, care selector, empty care. The original success predicate is separate.
(() => {
  const main = document.querySelector('#main-content');
  const assets = main?.querySelector('section[aria-label="저장된 자산 금액"]');
  const care = main?.querySelector('section[aria-labelledby="consumables-title"]');
  return [location.pathname === '/', !!main, !!assets, !!care,
    !!main?.querySelector('a[href="/login"]'),
    !!assets?.querySelector('[role="alert"]'), !!care?.querySelector('[role="alert"]'),
    !!assets && assets.textContent.includes('이 달에 저장한 금액은 아직 없어요.'),
    !!care?.querySelector('select'),
    !!care && care.textContent.includes('사용 중인 가전과 소모품 연결이 없어요.')
  ].map((value) => value ? '1' : '0').join('');
})();

// Test-only exact public messages -> fixed enum. Never return text or API data.
(() => {
  const care = document.querySelector('section[aria-labelledby="consumables-title"]');
  const alert = care?.querySelector(':scope > [role="alert"]');
  if (!alert) return 'NONE';
  const messages = {
    '서버 연결을 확인하지 못했어요. 연결 상태를 확인한 뒤 다시 시도해 주세요.': 'NETWORK',
    '이 작업을 할 권한이 없어요.': 'FORBIDDEN',
    '입력 형식과 필수 항목을 확인해 주세요.': 'VALIDATION',
    '앱의 네이티브 인증을 준비하고 있어요. 지금은 앱에서 로그인할 수 없어요.': 'NATIVE_UNAVAILABLE',
    '요청을 완료하지 못했어요. 잠시 후 다시 시도해 주세요.': 'REQUEST_FAILED',
    '다른 곳에서 정보가 변경됐어요. 작성한 내용은 그대로 두었어요. 서버의 최신 내용을 확인해 주세요.': 'CONFLICT',
    '요청 대기를 중단했어요. 서버에 반영됐을 수 있으니 현재 기록을 확인해 주세요. 같은 재고 입력으로 재시도하면 같은 작업을 확인해요.': 'CANCELLED'
  };
  return messages[alert.querySelector('p')?.textContent.trim()] ?? 'OTHER';
})();

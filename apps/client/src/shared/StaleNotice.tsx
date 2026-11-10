/** Shown beside records that stay on screen after a later refresh failed. */
export function StaleNotice({ retry, busy = false }: { retry: () => void; busy?: boolean }) {
  return (
    <p className="muted stale-notice" role="status">
      최신 내용을 불러오지 못해 앞서 불러온 내용을 보여 드려요.{" "}
      <button type="button" className="quiet-button" disabled={busy} onClick={retry}>
        다시 불러오기
      </button>
    </p>
  );
}

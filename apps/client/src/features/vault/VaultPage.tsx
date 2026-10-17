import { useState } from "react";
import { security, securityErrorMessage } from "../../platform/security";

export function VaultPage() {
  const [message, setMessage] = useState("");
  const [checking, setChecking] = useState(false);
  async function checkCapabilities() {
    setChecking(true);
    try {
      const result = await security.getCapabilities();
      setMessage(result.ok
        ? result.value.platform === "android"
          ? "Android 보안 모듈을 준비하고 있어요. 기기 보안과 보관함 등록 상태는 아직 확인할 수 없어요."
          : "PC 웹의 보관함 기능을 준비하고 있어요. CVC/CVV는 이 기기에서 제공하지 않음."
        : securityErrorMessage(result.code));
    } catch {
      setMessage("보안 기능의 상태를 확인하지 못했어요. 보호된 정보는 표시하지 않았어요.");
    } finally {
      setChecking(false);
    }
  }
  return (
    <>
      <div className="intro"><p className="eyebrow">보호된 카드 정보</p><h1>보관함</h1><p>카드의 보호된 정보와 기기 등록 상태를 관리하는 공간이에요.</p></div>
      <section className="card planned-state" aria-labelledby="vault-title">
        <span className="status-chip">사용 불가 · 준비 중</span>
        <h2 id="vault-title">보관함 기능을 준비하고 있어요</h2>
        <p>지금은 카드 정보 입력·열람, 기기 등록·복구와 잠금을 수행할 수 없어요.</p>
        <p className="muted">CVC/CVV는 Android 기기에서만 직접 입력하는 기능이에요. PC 웹에서는 제공하지 않으며 브라우저에 저장하지 않아요.</p>
        <button onClick={() => void checkCapabilities()} disabled={checking}>{checking ? "확인 중…" : "이 기기의 지원 상태 확인"}</button>
        <p className="support-message" role="status">{message}</p>
      </section>
    </>
  );
}

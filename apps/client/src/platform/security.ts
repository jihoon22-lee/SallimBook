import { Capacitor } from "@capacitor/core";
import type { SallimBookSecurity, SecurityCapabilities, SecurityErrorCode, SecurityResult } from "../../../../plugins/sallimbook-security/src/definitions";

export type { SallimBookSecurity, SecurityErrorCode } from "../../../../plugins/sallimbook-security/src/definitions";

/** SB-003 only supplies the boundary. SB-006/008 supply reviewed implementations.
 * Fail closed even if an unrelated native plugin happens to be registered.
 * Web CVC never falls back to localStorage, IndexedDB or another persistence API.
 */
export function createUnavailableSecurityAdapter(platform: SecurityCapabilities["platform"]): SallimBookSecurity {
  const unavailable = async <T>(): Promise<SecurityResult<T>> => ({ ok: false, code: platform === "android" ? "AUTH_UNAVAILABLE" : "UNSUPPORTED_PLATFORM" });
  return {
    async getCapabilities() {
      return { ok: true, value: { platform, available: false, supportedBiometrics: [], deviceSecure: null, vaultEnrolled: null, localCvcSupported: false } };
    },
    openCardSecretEditor: unavailable,
    showCardSecrets: unavailable,
    editLocalCvc: unavailable,
    deleteLocalCvc: unavailable,
    enrollDeviceVault: unavailable,
    lockVault: unavailable,
    forgetDeviceVault: unavailable,
  };
}

const currentPlatform = !Capacitor.isNativePlatform() ? "web" : Capacitor.getPlatform() === "android" ? "android" : "unsupported";
export const security = createUnavailableSecurityAdapter(currentPlatform);

const errorMessages: Record<SecurityErrorCode, string> = {
  AUTH_CANCELLED: "인증을 취소했어요. 보호된 정보는 표시하지 않았어요.",
  AUTH_UNAVAILABLE: "이 앱의 보안 기능은 아직 준비 중이에요. 보호된 정보를 입력하거나 표시할 수 없어요.",
  AUTH_LOCKED_OUT: "기기 인증이 잠겼어요. 기기의 인증 설정을 확인해 주세요.",
  KEY_INVALIDATED: "기기의 보관함 키를 사용할 수 없어요. 보관함 복구가 필요해요.",
  VAULT_NOT_ENROLLED: "이 기기에 보관함이 등록되어 있지 않아요.",
  SESSION_EXPIRED: "로그인이 만료되었어요. 다시 로그인해 주세요.",
  ACCESS_DENIED: "이 정보에 접근할 권한이 없어요.",
  CIPHER_INVALID: "보호된 정보를 확인하지 못했어요. 보관함 복구 안내를 확인해 주세요.",
  NETWORK_UNAVAILABLE: "연결을 확인하지 못했어요. 네트워크 상태를 확인해 주세요.",
  UNSUPPORTED_PLATFORM: "이 환경에서는 아직 보관함 기능을 사용할 수 없어요.",
};

export function securityErrorMessage(code: SecurityErrorCode): string { return errorMessages[code]; }

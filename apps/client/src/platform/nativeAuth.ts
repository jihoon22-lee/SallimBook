import { Capacitor, registerPlugin } from "@capacitor/core";
import type { NativeAuthResult, NativeMetadataRequest, SallimBookAuth } from "../../../../plugins/sallimbook-auth/src/definitions";
import { ApiError, apiErrorCode } from "./api";

const plugin = registerPlugin<SallimBookAuth>("SallimBookAuth");
export const isNativeAuth = () => Capacitor.isNativePlatform();
export const hasNativeAuth = () => Capacitor.getPlatform() === "android" && Capacitor.isPluginAvailable("SallimBookAuth");

async function invoke<T>(action: () => Promise<NativeAuthResult<T>>): Promise<T> {
  if (!hasNativeAuth()) throw new ApiError(0, "NATIVE_AUTH_UNAVAILABLE");
  let result: NativeAuthResult<T>;
  try { result = await action(); }
  catch { throw new ApiError(0, "NATIVE_AUTH_UNAVAILABLE"); }
  if (result.ok) return result.value;
  switch (result.code) {
    case "SESSION_EXPIRED": throw new ApiError(401, "UNAUTHENTICATED");
    case "NETWORK_UNAVAILABLE": throw new ApiError(0, "NETWORK_UNAVAILABLE");
    case "AUTH_CANCELLED": throw new ApiError(0, "REQUEST_CANCELLED");
    case "KEY_INVALIDATED": throw new ApiError(401, "NATIVE_KEY_INVALIDATED");
    case "ACCESS_DENIED": throw new ApiError(403, "FORBIDDEN");
    default: throw new ApiError(0, "NATIVE_AUTH_UNAVAILABLE");
  }
}

/** Native validates the path and projects each endpoint's safe metadata before bridging. */
export async function nativeRequest<T>(options: NativeMetadataRequest): Promise<T> {
  const response = await invoke(() => plugin.request(options));
  if (response.status < 200 || response.status >= 300) {
    const body = response.body as { error?: { code?: unknown } } | null;
    throw new ApiError(response.status, apiErrorCode(body?.error?.code, response.status));
  }
  return response.body as T;
}

export const nativeAuth = {
  getSession: () => invoke(() => plugin.getSession()),
  login: () => invoke(() => plugin.loginUI()),
  acceptInvitation: () => invoke(() => plugin.acceptInvitationUI()),
  createInvitation: () => invoke(() => plugin.createInvitationUI()),
  logout: () => invoke(() => plugin.logout()),
};

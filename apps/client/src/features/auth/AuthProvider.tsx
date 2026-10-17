import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { components } from "@sallimbook/api-client";
import { ApiError, apiClient, isNativeAuthUnavailable, requestApi, requireWebAuth, toApiError } from "../../platform/api";
import { isNativeAuth, nativeAuth, nativeRequest } from "../../platform/nativeAuth";

export type Member = components["schemas"]["MemberResponse"];
export type Device = components["schemas"]["DeviceResponse"];
type LoginInput = components["schemas"]["LoginRequest"];
type InvitationInput = components["schemas"]["InvitationAcceptance"];
type InvitationRequest = components["schemas"]["InvitationRequest"];
type Invitation = components["schemas"]["InvitationResponse"];
type DeviceList = components["schemas"]["DeviceListResponse"];

export type AuthState =
  | { status: "loading" }
  | { status: "signed-out"; remoteRevocationUnconfirmed?: boolean }
  | { status: "authenticated"; member: Member }
  | { status: "error"; error: ApiError }
  | { status: "native-unavailable" };

interface AuthContextValue {
  state: AuthState;
  reloadSession(): Promise<void>;
  login(input: LoginInput): Promise<void>;
  loginNative(): Promise<boolean>;
  logout(): Promise<void>;
  acceptInvitation(input: InvitationInput): Promise<Member>;
  createPartnerInvitation(input: InvitationRequest): Promise<Invitation>;
  listDevices(cursor?: string): Promise<DeviceList>;
  revokeDevice(device: Device): Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>(() => ({ status: isNativeAuthUnavailable() ? "native-unavailable" : "loading" }));
  const csrf = useRef<string | null>(null);
  const member = useRef<Member | null>(null);
  const generation = useRef(0);
  const mounted = useRef(false);
  const restoreFlight = useRef<Promise<void> | null>(null);
  const csrfFlight = useRef<{ generation: number; promise: Promise<string> } | null>(null);

  const ensureCurrent = useCallback((requestGeneration: number) => {
    if (!mounted.current || generation.current !== requestGeneration) throw new ApiError(0, "REQUEST_CANCELLED");
  }, []);

  const clearSession = useCallback(() => {
    generation.current += 1;
    csrf.current = null;
    member.current = null;
    if (mounted.current) setState({ status: "signed-out" });
  }, []);

  const renewCsrf = useCallback((requestGeneration: number): Promise<string> => {
    requireWebAuth();
    ensureCurrent(requestGeneration);
    if (csrfFlight.current?.generation === requestGeneration) return csrfFlight.current.promise;
    const promise = (async () => {
      const data = await requestApi(() => apiClient.GET("/api/v1/auth/web/csrf"));
      ensureCurrent(requestGeneration);
      if (!data?.csrf_token) throw new ApiError(0, "REQUEST_FAILED");
      csrf.current = data.csrf_token;
      return data.csrf_token;
    })();
    csrfFlight.current = { generation: requestGeneration, promise };
    void promise.finally(() => {
      if (csrfFlight.current?.promise === promise) csrfFlight.current = null;
    }).catch(() => {});
    return promise;
  }, [ensureCurrent]);

  const reloadSession = useCallback((): Promise<void> => {
    if (isNativeAuthUnavailable()) {
      csrf.current = null;
      member.current = null;
      setState({ status: "native-unavailable" });
      return Promise.resolve();
    }
    // React StrictMode and simultaneous retry consumers share one session restoration.
    if (restoreFlight.current) return restoreFlight.current;
    const requestGeneration = ++generation.current;
    csrf.current = null;
    member.current = null;
    setState({ status: "loading" });
    const promise = (async () => {
      try {
        if (isNativeAuth()) {
          const session = await nativeAuth.getSession();
          ensureCurrent(requestGeneration);
          if (!session.available) { setState({ status: "native-unavailable" }); return; }
          if (!session.authenticated) { setState({ status: "signed-out" }); return; }
        }
        const currentMember = isNativeAuth()
          ? await nativeRequest<Member>({ method: "GET", path: "/api/v1/me" })
          : await requestApi(() => apiClient.GET("/api/v1/me"));
        ensureCurrent(requestGeneration);
        if (!isNativeAuth()) await renewCsrf(requestGeneration);
        ensureCurrent(requestGeneration);
        member.current = currentMember;
        setState({ status: "authenticated", member: currentMember });
      } catch (error) {
        if (!mounted.current || requestGeneration !== generation.current) return;
        csrf.current = null;
        member.current = null;
        const failure = toApiError(error);
        setState(failure.status === 401 ? { status: "signed-out" } : { status: "error", error: failure });
      }
    })();
    restoreFlight.current = promise;
    void promise.finally(() => { if (restoreFlight.current === promise) restoreFlight.current = null; });
    return promise;
  }, [ensureCurrent, renewCsrf]);

  useEffect(() => {
    mounted.current = true;
    void reloadSession();
    return () => {
      mounted.current = false;
      csrf.current = null;
      member.current = null;
    };
  }, [reloadSession]);

  const authenticatedRequest = useCallback(async <T,>(request: (requestGeneration: number) => Promise<T>): Promise<T> => {
    if (!member.current) throw new ApiError(401, "UNAUTHENTICATED");
    const requestGeneration = generation.current;
    try {
      const data = await request(requestGeneration);
      ensureCurrent(requestGeneration);
      return data;
    } catch (error) {
      const failure = toApiError(error);
      if (failure.status === 401 && generation.current === requestGeneration) clearSession();
      throw failure;
    }
  }, [clearSession, ensureCurrent]);

  const mutation = useCallback(<T,>(request: (token: string) => Promise<T>): Promise<T> => authenticatedRequest(async (requestGeneration) => {
    requireWebAuth();
    const token = csrf.current ?? await renewCsrf(requestGeneration);
    try {
      return await request(token);
    } catch (error) {
      const failure = toApiError(error);
      if (failure.code !== "CSRF_FAILED") throw failure;
      // The server rejects CSRF before its handler. Retry this specific failure once only.
      // A sibling request may already have renewed the token; do not rotate it again.
      const refreshed = csrf.current && csrf.current !== token ? csrf.current : await renewCsrf(requestGeneration);
      ensureCurrent(requestGeneration);
      return request(refreshed);
    }
  }), [authenticatedRequest, ensureCurrent, renewCsrf]);

  const login = useCallback(async (input: LoginInput) => {
    requireWebAuth();
    if (member.current) {
      const currentMember = await mutation((token) => requestApi(() => apiClient.POST("/api/v1/auth/web/reauthenticate", {
        body: { password: input.password }, headers: { "X-CSRF-Token": token },
      })));
      member.current = currentMember;
      setState({ status: "authenticated", member: currentMember });
      return;
    }
    const requestGeneration = ++generation.current;
    const data = await requestApi(() => apiClient.POST("/api/v1/auth/web/login", { body: input }));
    ensureCurrent(requestGeneration);
    csrf.current = data.csrf_token;
    member.current = data.member;
    setState({ status: "authenticated", member: data.member });
  }, [ensureCurrent, mutation]);

  const loginNative = useCallback(async () => {
    if (!isNativeAuth()) throw new ApiError(0, "NATIVE_AUTH_UNAVAILABLE");
    const requestGeneration = ++generation.current;
    const result = member.current ? await nativeAuth.reauthenticate() : await nativeAuth.login();
    ensureCurrent(requestGeneration);
    if (result.status !== "authenticated") {
      // A native form may discover an expired session before the user closes it.
      // Restore the actual native state instead of keeping a stale authenticated view.
      await reloadSession();
      return false;
    }
    // Keep the native action mounted until it can navigate after success. A global
    // loading transition here would unmount its completion handler before navigation.
    try {
      const currentMember = await nativeRequest<Member>({ method: "GET", path: "/api/v1/me" });
      ensureCurrent(requestGeneration);
      csrf.current = null;
      member.current = currentMember;
      setState({ status: "authenticated", member: currentMember });
    } catch (error) {
      ensureCurrent(requestGeneration);
      member.current = null;
      const failure = toApiError(error);
      setState(failure.status === 401 ? { status: "signed-out" } : { status: "error", error: failure });
      throw failure;
    }
    return true;
  }, [ensureCurrent, reloadSession]);

  const logout = useCallback(async () => {
    if (isNativeAuth()) {
      const result = await nativeAuth.logout();
      clearSession();
      // Local credentials are removed even when a remote revocation cannot be confirmed.
      if (!result.serverRevoked && mounted.current) setState({ status: "signed-out", remoteRevocationUnconfirmed: true });
      return;
    }
    try {
      await mutation((token) => requestApi(() => apiClient.POST("/api/v1/auth/web/logout", { headers: { "X-CSRF-Token": token } })));
      clearSession();
    } catch (error) {
      if (toApiError(error).status !== 401) throw error;
      // A confirmed expired session is already signed out. Network failures are not success.
      clearSession();
    }
  }, [clearSession, mutation]);

  const acceptInvitation = useCallback(async (input: InvitationInput): Promise<Member> => {
    requireWebAuth();
    if (member.current) throw new ApiError(0, "ALREADY_AUTHENTICATED");
    // Registration returns a member, not an authenticated session. Do not pretend it logs in.
    return requestApi(() => apiClient.POST("/api/v1/auth/invitations/accept", { body: input }));
  }, []);

  const createPartnerInvitation = useCallback((input: InvitationRequest): Promise<Invitation> => mutation((token) => requestApi(() =>
    apiClient.POST("/api/v1/household/invitations", { body: input, headers: { "X-CSRF-Token": token } }),
  )), [mutation]);

  const listDevices = useCallback((cursor?: string): Promise<DeviceList> => authenticatedRequest(() => isNativeAuth()
    ? nativeRequest<DeviceList>({ method: "GET", path: `/api/v1/devices?limit=50${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}` })
    : requestApi(() =>
    apiClient.GET("/api/v1/devices", { params: { query: { limit: 50, ...(cursor ? { cursor } : {}) } } }),
  )), [authenticatedRequest]);

  const revokeDevice = useCallback(async (device: Device) => {
    if (!Number.isSafeInteger(device.version) || device.version < 1) throw new ApiError(400, "INVALID_VERSION");
    if (isNativeAuth()) await authenticatedRequest(() => nativeRequest({ method: "DELETE", path: `/api/v1/devices/${device.id}`, ifMatch: `"${device.version}"` }));
    else await mutation((token) => requestApi(() => apiClient.DELETE("/api/v1/devices/{device_id}", {
      params: { path: { device_id: device.id }, header: { "If-Match": `"${device.version}"` } },
      headers: { "X-CSRF-Token": token },
    })));
    if (device.current) clearSession();
  }, [authenticatedRequest, clearSession, mutation]);

  const value = useMemo(() => ({ state, reloadSession, login, loginNative, logout, acceptInvitation, createPartnerInvitation, listDevices, revokeDevice }),
    [state, reloadSession, login, loginNative, logout, acceptInvitation, createPartnerInvitation, listDevices, revokeDevice]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("AuthProvider is required");
  return context;
}

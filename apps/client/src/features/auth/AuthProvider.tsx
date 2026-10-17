import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { createApiClient } from "@sallimbook/api-client";
import type { components } from "@sallimbook/api-client";
import type { AuthenticatedApi, WriteClient, ScopeProof } from "./AuthenticatedApi";
import type { ApiResult } from "../../platform/api";
import { ApiError, apiClient, isNativeAuthUnavailable, requestApi, requireWebAuth, toApiError } from "../../platform/api";
import { isNativeAuth, nativeAuth, nativeRequest } from "../../platform/nativeAuth";
import { createPasskey, getPasskey } from "../../platform/webauthn";

export type Member = components["schemas"]["MemberResponse"];
export type Device = components["schemas"]["DeviceResponse"];
type LoginInput = components["schemas"]["LoginRequest"];
type InvitationInput = components["schemas"]["InvitationAcceptance"];
type InvitationRequest = components["schemas"]["InvitationRequest"];
type Invitation = components["schemas"]["InvitationResponse"];
type DeviceList = components["schemas"]["DeviceListResponse"];
export type Passkey = components["schemas"]["CredentialResponse"];
type PasskeyList = components["schemas"]["CredentialListResponse"];
type PasskeyLoginInput = components["schemas"]["LoginOptionsRequest"];
type StepUpPurpose = ScopeProof["purpose"];
export type OperationProof = { signal: AbortSignal; stepUp: boolean };

export type AuthState =
  | { status: "locked" }
  | { status: "loading" }
  | { status: "signed-out"; remoteRevocationUnconfirmed?: boolean }
  | { status: "authenticated"; member: Member }
  | { status: "error"; error: ApiError }
  | { status: "native-unavailable" };

interface AuthContextValue {
  state: AuthState;
  domainApi: AuthenticatedApi;
  reloadSession(): Promise<void>;
  login(input: LoginInput): Promise<void>;
  loginNative(passkey?: boolean): Promise<boolean>;
  loginPasskey(input: PasskeyLoginInput, signal: AbortSignal): Promise<void>;
  registerPasskey(label: string, signal: AbortSignal): Promise<boolean>;
  listPasskeys(cursor?: string): Promise<PasskeyList>;
  revokePasskey(passkey: Passkey): Promise<boolean>;
  logout(): Promise<void>;
  acceptInvitation(input: InvitationInput): Promise<Member>;
  createPartnerInvitation(input: InvitationRequest, proof?: OperationProof): Promise<Invitation>;
  listDevices(cursor?: string): Promise<DeviceList>;
  revokeDevice(device: Device, proof?: OperationProof): Promise<boolean>;
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

  const clearForAppLock = useCallback(() => {
    generation.current += 1;
    restoreFlight.current = null;
    csrf.current = null;
    member.current = null;
    if (mounted.current) setState({ status: "locked" });
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
        setState(failure.code === "APP_LOCKED" ? { status: "locked" } : failure.status === 401 ? { status: "signed-out" } : { status: "error", error: failure });
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

  useEffect(() => {
    if (!isNativeAuth() || isNativeAuthUnavailable()) return;
    let disposed = false;
    let handle: { remove(): Promise<void> } | undefined;
    void nativeAuth.onAppLock(({ locked }) => {
      if (disposed || !mounted.current) return;
      // Events discard UI state; native policy still decides whether any API may run.
      if (locked) clearForAppLock(); else void reloadSession();
    }).then((value) => { if (disposed) void value.remove(); else handle = value; })
      .catch(() => { if (!disposed) clearForAppLock(); });
    return () => { disposed = true; if (handle) void handle.remove(); };
  }, [clearForAppLock, reloadSession]);

  const authenticatedRequest = useCallback(async <T,>(request: (requestGeneration: number) => Promise<T>): Promise<T> => {
    if (!member.current) throw new ApiError(401, "UNAUTHENTICATED");
    const requestGeneration = generation.current;
    try {
      const data = await request(requestGeneration);
      ensureCurrent(requestGeneration);
      return data;
    } catch (error) {
      const failure = toApiError(error);
      if (failure.code === "APP_LOCKED") clearForAppLock();
      if (failure.status === 401 && failure.code !== "PASSKEY_VERIFICATION_FAILED" && generation.current === requestGeneration) clearSession();
      throw failure;
    }
  }, [clearSession, clearForAppLock, ensureCurrent]);

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

  const loginNative = useCallback(async (passkey = false) => {
    if (!isNativeAuth()) throw new ApiError(0, "NATIVE_AUTH_UNAVAILABLE");
    const requestGeneration = ++generation.current;
    const result = member.current ? await nativeAuth.reauthenticate() : await (passkey ? nativeAuth.loginPasskey() : nativeAuth.login());
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

  const scopedOperation = useCallback(<T,>(purpose: StepUpPurpose, targetId: string, signal: AbortSignal, action: (token: string, grant: string) => Promise<T>): Promise<T> => authenticatedRequest(async (requestGeneration) => {
    signal.throwIfAborted();
    const options = await mutation((token) => requestApi(() => apiClient.POST("/api/v1/auth/step-up/options", {
      body: { purpose, target_id: targetId }, headers: { "X-CSRF-Token": token }, signal,
    })));
    ensureCurrent(requestGeneration);
    const credential = await getPasskey(options, signal);
    ensureCurrent(requestGeneration);
    const grant = await mutation((token) => requestApi(() => apiClient.POST("/api/v1/auth/step-up/verify", {
      body: { challenge_id: options.challenge_id, credential }, headers: { "X-CSRF-Token": token }, signal,
    })));
    ensureCurrent(requestGeneration);
    signal.throwIfAborted();
    if (grant.purpose !== purpose || grant.target_id !== targetId) throw new ApiError(0, "STEP_UP_REQUIRED");
    // A grant stays in this call only and is consumed by this one exact operation.
    // It never updates session freshness, UI state, storage, or another operation.
    return mutation((token) => { signal.throwIfAborted(); return action(token, grant.grant_token); });
  }), [authenticatedRequest, mutation, ensureCurrent]);

  const loginPasskey = useCallback(async (input: PasskeyLoginInput, signal: AbortSignal) => {
    requireWebAuth();
    if (member.current) throw new ApiError(0, "ALREADY_AUTHENTICATED");
    signal.throwIfAborted();
    const requestGeneration = ++generation.current;
    const options = await requestApi(() => apiClient.POST("/api/v1/auth/web/passkeys/options", { body: input, signal }));
    ensureCurrent(requestGeneration);
    const credential = await getPasskey(options, signal);
    ensureCurrent(requestGeneration);
    const data = await requestApi(() => apiClient.POST("/api/v1/auth/web/passkeys/verify", { body: { challenge_id: options.challenge_id, credential }, signal }));
    ensureCurrent(requestGeneration);
    signal.throwIfAborted();
    csrf.current = data.csrf_token;
    member.current = data.member;
    setState({ status: "authenticated", member: data.member });
  }, [ensureCurrent]);

  const registerPasskey = useCallback((label: string, signal: AbortSignal): Promise<boolean> => authenticatedRequest(async (requestGeneration) => {
    signal.throwIfAborted();
    if (isNativeAuth()) {
      const result = await nativeAuth.registerPasskey();
      signal.throwIfAborted();
      return result.status === "registered";
    }
    const options = await mutation((token) => requestApi(() => apiClient.POST("/api/v1/auth/passkeys/register/options", { body: { label }, headers: { "X-CSRF-Token": token }, signal })));
    ensureCurrent(requestGeneration);
    const credential = await createPasskey(options, signal);
    ensureCurrent(requestGeneration);
    await mutation((token) => requestApi(() => apiClient.POST("/api/v1/auth/passkeys/register/verify", { body: { challenge_id: options.challenge_id, credential }, headers: { "X-CSRF-Token": token }, signal })));
    signal.throwIfAborted();
    return true;
  }), [authenticatedRequest, mutation, ensureCurrent]);

  const listPasskeys = useCallback((cursor?: string): Promise<PasskeyList> => authenticatedRequest(() => isNativeAuth()
    ? nativeRequest<PasskeyList>({ method: "GET", path: `/api/v1/auth/passkeys?limit=50${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}` })
    : requestApi(() => apiClient.GET("/api/v1/auth/passkeys", { params: { query: { limit: 50, ...(cursor ? { cursor } : {}) } } }))), [authenticatedRequest]);

  const revokePasskey = useCallback(async (passkey: Passkey): Promise<boolean> => {
    if (!Number.isSafeInteger(passkey.version) || passkey.version < 1) throw new ApiError(400, "INVALID_VERSION");
    if (isNativeAuth()) return authenticatedRequest(async () => (await nativeAuth.revokePasskey(passkey.id, `"${passkey.version}"`)).status === "revoked");
    await mutation((token) => requestApi(() => apiClient.DELETE("/api/v1/auth/passkeys/{credential_id}", {
      params: { path: { credential_id: passkey.id }, header: { "If-Match": `"${passkey.version}"` } }, headers: { "X-CSRF-Token": token },
    })));
    return true;
  }, [authenticatedRequest, mutation]);

  const createPartnerInvitation = useCallback((input: InvitationRequest, proof?: OperationProof): Promise<Invitation> => {
    const action = (token: string, grant?: string) => requestApi(() => apiClient.POST("/api/v1/household/invitations", {
      body: input, headers: { "X-CSRF-Token": token, ...(grant ? { "X-Step-Up-Token": grant } : {}) }, signal: proof?.signal,
    }));
    if (proof?.stepUp) {
      if (!member.current) throw new ApiError(401, "UNAUTHENTICATED");
      return scopedOperation("household.invite", member.current.household_id, proof.signal, action);
    }
    return mutation((token) => action(token));
  }, [mutation, scopedOperation]);

  const listDevices = useCallback((cursor?: string): Promise<DeviceList> => authenticatedRequest(() => isNativeAuth()
    ? nativeRequest<DeviceList>({ method: "GET", path: `/api/v1/devices?limit=50${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}` })
    : requestApi(() =>
    apiClient.GET("/api/v1/devices", { params: { query: { limit: 50, ...(cursor ? { cursor } : {}) } } }),
  )), [authenticatedRequest]);

  const revokeDevice = useCallback(async (device: Device, proof?: OperationProof): Promise<boolean> => {
    if (!Number.isSafeInteger(device.version) || device.version < 1) throw new ApiError(400, "INVALID_VERSION");
    if (isNativeAuth()) {
      if (proof?.stepUp) {
        const result = await authenticatedRequest(() => nativeAuth.revokeDevice(device.id, `"${device.version}"`));
        if (result.status !== "revoked") return false;
      } else await authenticatedRequest(() => nativeRequest({ method: "DELETE", path: `/api/v1/devices/${device.id}`, ifMatch: `"${device.version}"` }));
    }
    else {
      const action = (token: string, grant?: string) => requestApi(() => apiClient.DELETE("/api/v1/devices/{device_id}", {
        params: { path: { device_id: device.id }, header: { "If-Match": `"${device.version}"` } },
        headers: { "X-CSRF-Token": token, ...(grant ? { "X-Step-Up-Token": grant } : {}) }, signal: proof?.signal,
      }));
      if (proof?.stepUp) await scopedOperation("device.revoke", device.id, proof.signal, action);
      else await mutation((token) => action(token));
    }
    if (device.current) clearSession();
    return true;
  }, [authenticatedRequest, clearSession, mutation, scopedOperation]);

  const domainApi = useMemo<AuthenticatedApi>(() => ({
    read: <T,>(web: ((client: Pick<typeof apiClient, "GET">) => Promise<ApiResult<T>>) | undefined, native?: () => Promise<T>) => authenticatedRequest(() => {
      if (isNativeAuth()) {
        if (!native) throw new ApiError(0, "NATIVE_AUTH_UNAVAILABLE");
        return native();
      }
      if (!web) throw new ApiError(0, "REQUEST_FAILED");
      return requestApi(() => web({ GET: apiClient.GET }));
    }),
    write: <T,>(web: ((client: WriteClient) => Promise<ApiResult<T>>) | undefined, native?: () => Promise<T>, proof?: ScopeProof) => {
      if (isNativeAuth()) return authenticatedRequest(() => {
        if (!native) throw new ApiError(0, "NATIVE_AUTH_UNAVAILABLE");
        return native();
      });
      if (!web) return Promise.reject(new ApiError(0, "REQUEST_FAILED"));
      const action = (token: string, grant?: string) => {
        const client = createApiClient();
        client.use({ onRequest({ request }) {
          const url = new URL(request.url, window.location.origin);
          if (url.origin !== window.location.origin || !url.pathname.startsWith("/api/v1/")) throw new ApiError(0, "ORIGIN_REJECTED");
          request.headers.set("X-CSRF-Token", token);
          if (grant) request.headers.set("X-Step-Up-Token", grant);
          return request;
        } });
        // Middleware and its private proof values stay inside this one request attempt.
        return requestApi(() => web({ POST: client.POST, PATCH: client.PATCH, PUT: client.PUT, DELETE: client.DELETE }));
      };
      return proof ? scopedOperation(proof.purpose, proof.targetId, proof.signal, action) : mutation((token) => action(token));
    },
  }), [authenticatedRequest, mutation, scopedOperation]);

  const value = useMemo(() => ({ state, domainApi, reloadSession, login, loginNative, loginPasskey, registerPasskey, listPasskeys, revokePasskey, logout, acceptInvitation, createPartnerInvitation, listDevices, revokeDevice }),
    [state, domainApi, reloadSession, login, loginNative, loginPasskey, registerPasskey, listPasskeys, revokePasskey, logout, acceptInvitation, createPartnerInvitation, listDevices, revokeDevice]);
  return <AuthContext.Provider value={value}>{state.status === "locked"
    ? <p role="status">앱이 잠겨 있어요. Android 보호 화면에서 다시 열어 주세요.</p>
    : children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("AuthProvider is required");
  return context;
}

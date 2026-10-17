import type { components } from "@sallimbook/api-client";
import { ApiError, requireWebAuth } from "./api";

type Options = components["schemas"]["OptionsResponse"];
type Registration = components["schemas"]["RegistrationCredential"];
type Assertion = components["schemas"]["AuthenticationCredential"];

export function supportsWebAuthn(): boolean {
  return window.isSecureContext && typeof PublicKeyCredential !== "undefined"
    && typeof PublicKeyCredential.parseCreationOptionsFromJSON === "function"
    && typeof PublicKeyCredential.parseRequestOptionsFromJSON === "function"
    && typeof navigator.credentials?.create === "function" && typeof navigator.credentials?.get === "function";
}

/** Canonical unpadded base64url, built only from the browser-returned binary value. */
function encode(value: ArrayBuffer): string {
  let bytes = "";
  for (const byte of new Uint8Array(value)) bytes += String.fromCharCode(byte);
  return btoa(bytes).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function ready(options: Options, signal: AbortSignal) {
  requireWebAuth();
  signal.throwIfAborted();
  if (!supportsWebAuthn()) throw new ApiError(0, "PASSKEY_UNSUPPORTED");
  if (document.visibilityState !== "visible") throw new ApiError(0, "REQUEST_CANCELLED");
  if (!Number.isFinite(Date.parse(options.expires_at)) || Date.parse(options.expires_at) <= Date.now()) throw new ApiError(0, "PASSKEY_EXPIRED");
}

function credential(value: Credential | null): PublicKeyCredential {
  if (!(value instanceof PublicKeyCredential) || value.type !== "public-key" || value.id !== encode(value.rawId)) throw new ApiError(0, "PASSKEY_FAILED");
  return value;
}

function attachment(value: PublicKeyCredential): Registration["authenticatorAttachment"] {
  return value.authenticatorAttachment === "platform" || value.authenticatorAttachment === "cross-platform" ? value.authenticatorAttachment : null;
}

function extensionResults(value: PublicKeyCredential): Registration["clientExtensionResults"] {
  // Only the server's generated allowlist crosses the API. In particular, never send PRF output.
  const properties = value.getClientExtensionResults().credProps;
  return typeof properties?.rk === "boolean" ? { credProps: { rk: properties.rk } } : {};
}

export function passkeyError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;
  if (error instanceof DOMException) {
    if (error.name === "AbortError") return new ApiError(0, "REQUEST_CANCELLED");
    if (error.name === "NotAllowedError") return new ApiError(0, "PASSKEY_CANCELLED");
    if (error.name === "InvalidStateError") return new ApiError(409, "CREDENTIAL_UNAVAILABLE");
    if (error.name === "NotSupportedError") return new ApiError(0, "PASSKEY_UNSUPPORTED");
    if (error.name === "SecurityError") return new ApiError(0, "PASSKEY_CONFIGURATION_INVALID");
  }
  return new ApiError(0, "PASSKEY_FAILED");
}

export async function createPasskey(options: Options, signal: AbortSignal): Promise<Registration> {
  try {
    ready(options, signal);
    const publicKey = PublicKeyCredential.parseCreationOptionsFromJSON(options.public_key as unknown as PublicKeyCredentialCreationOptionsJSON);
    const result = credential(await navigator.credentials.create({ publicKey, signal }));
    signal.throwIfAborted();
    if (!(result.response instanceof AuthenticatorAttestationResponse)) throw new ApiError(0, "PASSKEY_FAILED");
    const transports = result.response.getTransports().filter((item): item is NonNullable<Registration["response"]["transports"]>[number] => ["usb", "nfc", "ble", "smart-card", "internal", "cable", "hybrid"].includes(item));
    return { id: encode(result.rawId), rawId: encode(result.rawId), type: "public-key", authenticatorAttachment: attachment(result),
      response: { clientDataJSON: encode(result.response.clientDataJSON), attestationObject: encode(result.response.attestationObject), transports },
      clientExtensionResults: extensionResults(result) };
  } catch (error) { throw passkeyError(error); }
}

export async function getPasskey(options: Options, signal: AbortSignal): Promise<Assertion> {
  try {
    ready(options, signal);
    const publicKey = PublicKeyCredential.parseRequestOptionsFromJSON(options.public_key as unknown as PublicKeyCredentialRequestOptionsJSON);
    const result = credential(await navigator.credentials.get({ publicKey, signal }));
    signal.throwIfAborted();
    if (!(result.response instanceof AuthenticatorAssertionResponse)) throw new ApiError(0, "PASSKEY_FAILED");
    return { id: encode(result.rawId), rawId: encode(result.rawId), type: "public-key", authenticatorAttachment: attachment(result),
      response: { clientDataJSON: encode(result.response.clientDataJSON), authenticatorData: encode(result.response.authenticatorData), signature: encode(result.response.signature), userHandle: result.response.userHandle ? encode(result.response.userHandle) : null },
      clientExtensionResults: extensionResults(result) };
  } catch (error) { throw passkeyError(error); }
}

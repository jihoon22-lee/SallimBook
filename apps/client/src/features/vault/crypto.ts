import type { components } from "@sallimbook/api-client";

type Schema = components["schemas"];
export type Bytes = Uint8Array<ArrayBuffer>;
export type Scope = { householdId: string; keyVersion: number };
export type MemberWrap = Schema["MemberWrappingInput"];
export type RecoveryWrap = Schema["RecoveryWrappingInput"];
export type KeyCheck = Schema["KeyCheckInput"];
export type CardEnvelope = Schema["CardEnvelopeInput"];

const encoder = new TextEncoder();
const checkText = encoder.encode("SallimBook vault key check v1");
const recoveryInfo = encoder.encode("SallimBook/vault/recovery-kek/v1");
export const MIN_ITERATIONS = 600_000;
const MAX_ITERATIONS = 2_000_000;

/** Never include input, a browser crypto exception, or an opaque response in an error. */
export class VaultCryptoError extends Error {
  constructor() { super("보관함 암호와 보호된 데이터의 상태를 확인해 주세요."); this.name = "VaultCryptoError"; }
}
function requireValue(value: unknown): asserts value { if (!value) throw new VaultCryptoError(); }
export function wipe(value: Bytes | null | undefined) { value?.fill(0); }
export function randomBytes(size: number): Bytes {
  requireValue(size === 12 || size === 16 || size === 32);
  requireValue(globalThis.isSecureContext && !!globalThis.crypto?.subtle);
  return crypto.getRandomValues(new Uint8Array(size));
}
export function encode64(bytes: Bytes): string {
  requireValue(bytes.length <= 64);
  return btoa(String.fromCharCode(...bytes)).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}
export function decode64(value: string, length: number): Bytes {
  requireValue(Number.isSafeInteger(length) && length > 0 && length <= 64);
  requireValue(typeof value === "string" && value.length === Math.ceil(length * 8 / 6) && /^[A-Za-z0-9_-]+$/.test(value));
  let bytes: Bytes | null = null;
  try {
    const raw = atob(value.replaceAll("-", "+").replaceAll("_", "/") + "=".repeat((4 - value.length % 4) % 4));
    bytes = Uint8Array.from(raw, (char) => char.charCodeAt(0));
    requireValue(bytes.length === length && encode64(bytes) === value);
    return bytes;
  } catch { wipe(bytes); throw new VaultCryptoError(); }
}
export function passwordBytes(value: string, creating = false): Bytes {
  requireValue(typeof value === "string" && value.length <= 1024);
  const characters = [...value];
  requireValue(characters.length >= (creating ? 12 : 1));
  requireValue(characters.every((char) => char.length !== 1 || char.charCodeAt(0) < 0xd800 || char.charCodeAt(0) > 0xdfff));
  const bytes = encoder.encode(value); // Original UTF-8, without trimming or normalization.
  if (bytes.length > 1024) { wipe(bytes); throw new VaultCryptoError(); }
  return bytes;
}
function version(value: number): number { requireValue(Number.isSafeInteger(value) && value >= 1); return value; }
function iterations(value: number): number { requireValue(Number.isInteger(value) && value >= MIN_ITERATIONS && value <= MAX_ITERATIONS); return value; }
function uuid(value: string): Bytes {
  requireValue(typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value));
  return Uint8Array.from(value.replaceAll("-", "").match(/../g)!, (part) => Number.parseInt(part, 16));
}
function u64(value: number): Bytes { const bytes = new Uint8Array(8); new DataView(bytes.buffer).setBigUint64(0, BigInt(version(value)), false); return bytes; }
function u32(value: number): Bytes { requireValue(Number.isInteger(value) && value >= 1 && value <= 0xffffffff); const bytes = new Uint8Array(4); new DataView(bytes.buffer).setUint32(0, value, false); return bytes; }
function concat(...parts: Bytes[]): Bytes { const result = new Uint8Array(parts.reduce((total, part) => total + part.length, 0)); let offset = 0; for (const part of parts) { result.set(part, offset); offset += part.length; } return result; }
function prefix(kind: "card" | "member" | "recovery" | "key-check", householdId: string): Bytes { return concat(encoder.encode(`SallimBook/vault/${kind}/v1\0`), uuid(householdId)); }
function salt16(salt: Bytes): Bytes { requireValue(salt.length === 16); return salt; }
export const cardAad = (scope: Scope, cardId: string): Bytes => concat(prefix("card", scope.householdId), uuid(cardId), u64(scope.keyVersion), u32(1));
export const memberAad = (scope: Scope, memberId: string, generation: number, count: number, salt: Bytes): Bytes => concat(prefix("member", scope.householdId), uuid(memberId), u64(scope.keyVersion), u64(generation), u32(iterations(count)), salt16(salt));
export const recoveryAad = (scope: Scope, generation: number, salt: Bytes): Bytes => concat(prefix("recovery", scope.householdId), u64(scope.keyVersion), u64(generation), salt16(salt));
export const checkAad = (scope: Scope): Bytes => concat(prefix("key-check", scope.householdId), u64(scope.keyVersion));

async function gcm(key: CryptoKey, nonce: Bytes, aad: Bytes, value: Bytes, decrypt: boolean): Promise<Bytes> {
  requireValue(nonce.length === 12 && aad.length <= 128 && value.length <= 64);
  try { return new Uint8Array(await crypto.subtle[decrypt ? "decrypt" : "encrypt"]({ name: "AES-GCM", iv: nonce, additionalData: aad, tagLength: 128 }, key, value)); }
  catch { throw new VaultCryptoError(); }
}
export async function memberKek(password: Bytes, salt: Bytes, count: number): Promise<CryptoKey> {
  requireValue(password.length >= 1 && password.length <= 1024); salt16(salt); iterations(count);
  try {
    const material = await crypto.subtle.importKey("raw", password, "PBKDF2", false, ["deriveKey"]);
    return await crypto.subtle.deriveKey({ name: "PBKDF2", hash: "SHA-256", salt, iterations: count }, material, { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
  } catch { throw new VaultCryptoError(); }
}
export async function recoveryKek(code: Bytes, salt: Bytes): Promise<CryptoKey> {
  requireValue(code.length === 32); salt16(salt);
  try {
    const material = await crypto.subtle.importKey("raw", code, "HKDF", false, ["deriveKey"]);
    return await crypto.subtle.deriveKey({ name: "HKDF", hash: "SHA-256", salt, info: recoveryInfo }, material, { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
  } catch { throw new VaultCryptoError(); }
}

/** Owns raw HVK bytes only inside this module; callers can destroy but cannot extract them. */
export class VaultKey {
  #bytes: Bytes | null;
  private constructor(bytes: Bytes) { requireValue(bytes.length === 32); this.#bytes = bytes; }
  static generate(): VaultKey { return new VaultKey(randomBytes(32)); }
  static async unwrap(kek: CryptoKey, nonce: Bytes, aad: Bytes, wrapped: Bytes): Promise<VaultKey> {
    requireValue(wrapped.length === 48);
    const raw = await gcm(kek, nonce, aad, wrapped, true);
    if (raw.length !== 32) { wipe(raw); throw new VaultCryptoError(); }
    return new VaultKey(raw);
  }
  destroy() { wipe(this.#bytes); this.#bytes = null; }
  /** In-memory continuity proof only; never persist or send this digest. */
  async fingerprint(): Promise<string> {
    const raw = this.#require().slice();
    try { const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", raw)); this.#require(); return encode64(digest); }
    finally { wipe(raw); }
  }
  #require(): Bytes { requireValue(this.#bytes !== null); return this.#bytes; }
  async #operate(nonce: Bytes, aad: Bytes, value: Bytes, decrypt: boolean): Promise<Bytes> {
    const key = await crypto.subtle.importKey("raw", this.#require(), "AES-GCM", false, ["encrypt", "decrypt"]);
    this.#require();
    const result = await gcm(key, nonce, aad, value, decrypt);
    if (this.#bytes === null) { wipe(result); throw new VaultCryptoError(); }
    return result;
  }
  encrypt(nonce: Bytes, aad: Bytes, plain: Bytes) { return this.#operate(nonce, aad, plain, false); }
  decrypt(nonce: Bytes, aad: Bytes, cipher: Bytes) { return this.#operate(nonce, aad, cipher, true); }
  async wrap(kek: CryptoKey, nonce: Bytes, aad: Bytes): Promise<Bytes> {
    const raw = this.#require().slice();
    try {
      const result = await gcm(kek, nonce, aad, raw, false);
      this.#require();
      return result;
    } finally { wipe(raw); }
  }
}

function envelopeScope(row: { format_version: number; key_version: number }, scope: Scope) {
  requireValue(row.format_version === 1 && row.key_version === version(scope.keyVersion)); uuid(scope.householdId);
}
export async function verifyKey(key: VaultKey, scope: Scope, row: KeyCheck): Promise<void> {
  envelopeScope(row, scope);
  const nonce = decode64(row.nonce, 12), cipher = decode64(row.ciphertext, 45);
  const plain = await key.decrypt(nonce, checkAad(scope), cipher);
  try { requireValue(plain.length === checkText.length && plain.every((byte, index) => byte === checkText[index])); }
  finally { wipe(plain); }
}
export async function makeKeyCheck(key: VaultKey, scope: Scope): Promise<KeyCheck> {
  const nonce = randomBytes(12), cipher = await key.encrypt(nonce, checkAad(scope), checkText);
  return { format_version: 1, key_version: scope.keyVersion, nonce: encode64(nonce), ciphertext: encode64(cipher) };
}
export async function unwrapMember(password: Bytes, scope: Scope, memberId: string, row: MemberWrap, check: KeyCheck): Promise<VaultKey> {
  envelopeScope(row, scope); requireValue(row.member_id === memberId && row.kdf === "PBKDF2-HMAC-SHA256");
  const salt = decode64(row.salt, 16), nonce = decode64(row.nonce, 12), wrapped = decode64(row.wrapped_hvk, 48);
  const key = await VaultKey.unwrap(await memberKek(password, salt, row.iterations), nonce, memberAad(scope, memberId, row.generation, row.iterations, salt), wrapped);
  try { await verifyKey(key, scope, check); return key; } catch { key.destroy(); throw new VaultCryptoError(); }
}
export async function wrapMember(key: VaultKey, password: Bytes, scope: Scope, memberId: string, generation: number): Promise<MemberWrap> {
  const salt = randomBytes(16), nonce = randomBytes(12), count = MIN_ITERATIONS;
  const wrapped = await key.wrap(await memberKek(password, salt, count), nonce, memberAad(scope, memberId, generation, count, salt));
  return { format_version: 1, key_version: scope.keyVersion, member_id: memberId, generation, kdf: "PBKDF2-HMAC-SHA256", iterations: count, salt: encode64(salt), nonce: encode64(nonce), wrapped_hvk: encode64(wrapped) };
}
export async function unwrapRecovery(code: Bytes, scope: Scope, row: RecoveryWrap, check: KeyCheck): Promise<VaultKey> {
  envelopeScope(row, scope); requireValue(row.kdf === "HKDF-SHA256");
  const salt = decode64(row.salt, 16), nonce = decode64(row.nonce, 12), wrapped = decode64(row.wrapped_hvk, 48);
  const key = await VaultKey.unwrap(await recoveryKek(code, salt), nonce, recoveryAad(scope, row.generation, salt), wrapped);
  try { await verifyKey(key, scope, check); return key; } catch { key.destroy(); throw new VaultCryptoError(); }
}
export async function wrapRecovery(key: VaultKey, code: Bytes, scope: Scope, generation: number): Promise<RecoveryWrap> {
  const salt = randomBytes(16), nonce = randomBytes(12);
  const wrapped = await key.wrap(await recoveryKek(code, salt), nonce, recoveryAad(scope, generation, salt));
  return { format_version: 1, key_version: scope.keyVersion, generation, kdf: "HKDF-SHA256", salt: encode64(salt), nonce: encode64(nonce), wrapped_hvk: encode64(wrapped) };
}

function validPan(pan: Bytes): boolean {
  if (pan.length < 13 || pan.length > 19 || pan.some((digit) => digit < 48 || digit > 57)) return false;
  let sum = 0;
  for (let index = pan.length - 1; index >= 0; index--) {
    let digit = pan[index]! - 48;
    if ((pan.length - 1 - index) % 2 === 1) { digit *= 2; if (digit > 9) digit -= 9; }
    sum += digit;
  }
  return sum % 10 === 0;
}
export function cardPayload(pan: string, year: number, month: number): Bytes {
  requireValue(typeof pan === "string" && /^[0-9]{13,19}$/.test(pan));
  requireValue(Number.isInteger(year) && year >= 2000 && year <= 2199 && Number.isInteger(month) && month >= 1 && month <= 12);
  const digits = encoder.encode(pan);
  try {
    requireValue(validPan(digits));
    const plain = new Uint8Array(27); plain.set(encoder.encode("SBV1")); plain[4] = digits.length; plain.set(digits, 5);
    new DataView(plain.buffer).setUint16(24, year, false); plain[26] = month;
    return plain;
  } finally { wipe(digits); }
}
function checkPayload(plain: Bytes): number {
  requireValue(plain.length === 27 && plain[0] === 83 && plain[1] === 66 && plain[2] === 86 && plain[3] === 49);
  const length = plain[4]!;
  requireValue(length >= 13 && length <= 19);
  const pan = plain.slice(5, 5 + length);
  try { requireValue(validPan(pan)); } finally { wipe(pan); }
  requireValue(plain.slice(5 + length, 24).every((byte) => byte === 0));
  const year = new DataView(plain.buffer, plain.byteOffset, plain.byteLength).getUint16(24, false);
  requireValue(year >= 2000 && year <= 2199 && plain[26]! >= 1 && plain[26]! <= 12);
  return length;
}
export function lastFour(plain: Bytes): string {
  const length = checkPayload(plain);
  return String.fromCharCode(...plain.subarray(5 + length - 4, 5 + length));
}
/** Use only in a dedicated transient DOM output. Never put this string in React state/cache. */
export function displayCard(plain: Bytes): string {
  const length = checkPayload(plain);
  const year = new DataView(plain.buffer, plain.byteOffset, plain.byteLength).getUint16(24, false);
  return `${String.fromCharCode(...plain.subarray(5, 5 + length))} · ${year}/${String(plain[26]).padStart(2, "0")}`;
}
export async function encryptCard(key: VaultKey, scope: Scope, cardId: string, plain: Bytes): Promise<CardEnvelope> {
  const last_four = lastFour(plain), nonce = randomBytes(12);
  const cipher = await key.encrypt(nonce, cardAad(scope, cardId), plain);
  return { format_version: 1, key_version: scope.keyVersion, payload_schema_version: 1, last_four, nonce: encode64(nonce), ciphertext: encode64(cipher) };
}
export async function decryptCard(key: VaultKey, scope: Scope, cardId: string, row: CardEnvelope): Promise<Bytes> {
  envelopeScope(row, scope); requireValue(row.payload_schema_version === 1);
  const plain = await key.decrypt(decode64(row.nonce, 12), cardAad(scope, cardId), decode64(row.ciphertext, 43));
  try { requireValue(lastFour(plain) === row.last_four); return plain; }
  catch { wipe(plain); throw new VaultCryptoError(); }
}

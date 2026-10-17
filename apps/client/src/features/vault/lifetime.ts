import { VaultCryptoError, VaultKey, wipe } from "./crypto";
import type { Bytes } from "./crypto";

/** One foreground operation owns every key, mutable secret and transient DOM field. */
export class VaultLifetime {
  readonly controller = new AbortController();
  readonly signal = this.controller.signal;
  #keys = new Set<VaultKey>();
  #bytes = new Set<Bytes>();
  #closed = false;
  #deadline: ReturnType<typeof setTimeout> | undefined;
  #display: ReturnType<typeof setTimeout> | undefined;
  #poll: ReturnType<typeof setInterval> | undefined;
  #polling = false;
  #started = performance.now();
  constructor(private readonly root: HTMLElement, private readonly locked: () => void) {
    window.addEventListener("blur", this.close);
    window.addEventListener("pagehide", this.close);
    document.addEventListener("visibilitychange", this.hidden);
    root.addEventListener("input", this.touch);
    this.touch();
  }
  private hidden = () => { if (document.visibilityState !== "visible") this.close(); };
  private touch = () => {
    if (this.#closed) return;
    if (this.#deadline) clearTimeout(this.#deadline);
    // User input extends an idle form up to five minutes; network/KDF work does not.
    const remaining = Math.min(60_000, 300_000 - (performance.now() - this.#started));
    if (remaining <= 0) { this.close(); return; }
    this.#deadline = setTimeout(this.close, remaining);
  };
  assert() {
    if (this.#closed || this.signal.aborted || document.visibilityState !== "visible" || !document.hasFocus()) {
      this.close(); throw new VaultCryptoError();
    }
  }
  ownKey(key: VaultKey): VaultKey {
    if (this.#closed) { key.destroy(); throw new VaultCryptoError(); }
    this.#keys.add(key); return key;
  }
  ownBytes(value: Bytes): Bytes {
    if (this.#closed) { wipe(value); throw new VaultCryptoError(); }
    this.#bytes.add(value); return value;
  }
  forgetBytes(value: Bytes) { wipe(value); this.#bytes.delete(value); }
  forgetKey(key: VaultKey) { key.destroy(); this.#keys.delete(key); }
  clearSecrets() {
    for (const key of this.#keys) key.destroy(); this.#keys.clear();
    for (const value of this.#bytes) wipe(value); this.#bytes.clear();
    this.clearDom();
  }
  clearDom() {
    for (const field of this.root.querySelectorAll<HTMLInputElement>("input[data-vault-secret]")) field.value = "";
    for (const output of this.root.querySelectorAll<HTMLElement>("[data-vault-output]")) output.textContent = "";
  }
  beginStep() {
    this.assert();
    if (this.#deadline) clearTimeout(this.#deadline);
    this.#deadline = setTimeout(this.close, 60_000);
  }
  waitForInput() { this.assert(); this.#started = performance.now(); this.touch(); }
  showFor30Seconds(revalidate: () => Promise<void>) {
    this.assert();
    if (this.#display) clearTimeout(this.#display);
    this.#display = setTimeout(this.close, 30_000);
    if (this.#poll) clearInterval(this.#poll);
    this.#poll = setInterval(() => {
      if (this.#polling || this.#closed) return;
      this.#polling = true;
      void revalidate().then(() => this.assert()).catch(this.close).finally(() => { this.#polling = false; });
    }, 5_000);
  }
  close = () => {
    if (this.#closed) return;
    this.#closed = true; this.controller.abort();
    if (this.#deadline) clearTimeout(this.#deadline);
    if (this.#display) clearTimeout(this.#display);
    if (this.#poll) clearInterval(this.#poll);
    window.removeEventListener("blur", this.close);
    window.removeEventListener("pagehide", this.close);
    document.removeEventListener("visibilitychange", this.hidden);
    this.root.removeEventListener("input", this.touch);
    this.clearSecrets(); this.locked();
  };
}

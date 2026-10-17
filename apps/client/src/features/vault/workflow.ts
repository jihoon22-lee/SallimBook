import type { components } from "@sallimbook/api-client";
import { ApiError } from "../../platform/api";
import type { WebVaultRequest } from "./actions";
import { VaultCryptoError, VaultKey, decryptCard, displayCard, encryptCard, makeKeyCheck, randomBytes, unwrapMember, unwrapRecovery, wrapMember, wrapRecovery, encode64 } from "./crypto";
import type { Bytes, Scope } from "./crypto";
import { VaultLifetime } from "./lifetime";
import type { PrivateVaultApi } from "./privateApi";

type S = components["schemas"];
export type VaultPublicContext = {
  status: S["VaultStatusResponse"];
  members: S["MemberResponse"][];
  card?: S["CardResponse"];
  offer?: S["VaultShareResponse"];
  rotation?: S["VaultRotationResponse"];
};
export type VaultInputs = {
  password?: Bytes;
  stagedPassword?: Bytes;
  recoveryCode?: Bytes;
  newPasswords: Map<string, Bytes>;
  card?: Bytes;
  reason: S["VaultRotationStart"]["reason"];
};
export type WorkflowResult = "completed" | "displayed" | "confirm-recovery";
export const needsReauthentication = (error: unknown) => error instanceof ApiError && ["REAUTHENTICATION_REQUIRED", "STEP_UP_REQUIRED"].includes(error.code);
function check(value: unknown, conflict = false): asserts value {
  if (!value) throw new ApiError(conflict ? 409 : 403, conflict ? "VERSION_CONFLICT" : "FORBIDDEN");
}
function secret(value: Bytes | undefined): Bytes { if (!value) throw new VaultCryptoError(); return value; }
function advance(value: number): number { check(Number.isSafeInteger(value) && value >= 1 && value < Number.MAX_SAFE_INTEGER); return value + 1; }

/** No method returns keys, opaque envelopes or plaintext into React state. */
export class VaultWorkflow {
  context: VaultPublicContext | null = null;
  #prepared: (() => Promise<void>) | null = null;
  #retry: (() => Promise<unknown>) | null = null;
  // Only immutable manifest identifiers and digests survive a same-screen reauthentication.
  #cursor: { binding: string; oldKey: string; newKey: string; verified: Set<string> } | null = null;
  constructor(
    private readonly api: PrivateVaultApi,
    private readonly me: S["MemberResponse"],
    readonly request: WebVaultRequest,
    private readonly life: VaultLifetime,
    private readonly recoveryOutput: (text: string) => void,
    private readonly cardOutput: (text: string) => void,
  ) {}
  get canRetry(): boolean { return this.#retry !== null; }
  dispose() { this.#prepared = null; this.#retry = null; this.#cursor = null; this.context = null; }
  private get signal() { return this.life.signal; }
  private current(): VaultPublicContext { check(this.context); this.life.assert(); return this.context; }
  private scope(status = this.current().status): Scope {
    check(status.household_id === this.me.household_id && status.initialized && status.current_key_version !== null);
    check(Number.isSafeInteger(status.current_key_version) && status.current_key_version >= 1);
    return { householdId: this.me.household_id, keyVersion: status.current_key_version };
  }
  private validateStatus(status: S["VaultStatusResponse"]) {
    check(status.household_id === this.me.household_id);
    check(status.initialized ? status.id !== null && status.version !== null && status.current_key_version !== null : status.id === null && status.version === null && status.current_key_version === null);
    if (status.initialized) {
      this.scope(status);
      check(Number.isSafeInteger(status.version) && status.version! >= 1);
      check(status.members.length >= 1 && status.members.length <= 2 && new Set(status.members.map((m) => m.member_id)).size === status.members.length);
      check(status.members.find((m) => m.member_id === this.me.member_id)?.status === status.own_membership);
    }
  }
  private async findOffer(id: string): Promise<S["VaultShareResponse"]> {
    let cursor: string | undefined;
    const seen = new Set<string>();
    do {
      this.life.assert();
      const page = await this.api.shares(this.signal, cursor);
      check(page.items.length <= 200 && page.items.every((item) => item.household_id === this.me.household_id && [item.source_member_id, item.target_member_id].includes(this.me.member_id)));
      const found = page.items.find((item) => item.id === id); if (found) return found;
      cursor = page.next_cursor ?? undefined;
      if (cursor) { check(!seen.has(cursor) && seen.size < 1000); seen.add(cursor); }
    } while (cursor);
    throw new ApiError(404, "NOT_FOUND");
  }
  async load(): Promise<VaultPublicContext> {
    const [status, members] = await Promise.all([this.api.status(this.signal), this.api.members(this.signal)]);
    this.validateStatus(status);
    check(members.length >= 1 && members.length <= 2 && members.every((member) => member.household_id === this.me.household_id));
    check(members.find((member) => member.member_id === this.me.member_id)?.user_id === this.me.user_id);
    check(new Set(members.map((member) => member.member_id)).size === members.length);
    const context: VaultPublicContext = { status, members };
    const r = this.request;
    if (r.action === "setup") check(!status.initialized, true);
    else {
      check(status.initialized, true);
      if (!["accept-share", "cancel-share"].includes(r.action)) check(status.own_membership === "active");
    }
    if ("cardId" in r) {
      context.card = await this.api.cardMetadata(r.cardId, this.signal);
      check(context.card.id === r.cardId && context.card.household_id === this.me.household_id);
    }
    if ("offerId" in r) {
      context.offer = await this.findOffer(r.offerId);
      check(context.offer.state === "pending" && context.offer.key_version === status.current_key_version, true);
      if (r.action === "accept-share") check(context.offer.target_member_id === this.me.member_id);
    }
    if ("memberId" in r) check(status.members.some((member) => member.member_id === r.memberId));
    if ("rotationId" in r) {
      context.rotation = await this.api.rotation(r.rotationId, this.signal);
      check(context.rotation.id === r.rotationId);
      this.checkRotation(context.rotation, status);
    }
    this.life.assert(); this.context = context; return context;
  }
  private checkRotation(rotation: S["VaultRotationResponse"], status: S["VaultStatusResponse"]) {
    check(rotation.household_id === this.me.household_id && rotation.state === "staging" && status.pending_rotation_id === rotation.id, true);
    check(rotation.source_key_version === status.current_key_version && rotation.key_version > rotation.source_key_version, true);
    check(Number.isSafeInteger(rotation.key_version) && Number.isSafeInteger(rotation.version) && rotation.version >= 1);
    const members = status.members.filter((member) => member.status === "active");
    check(rotation.members.length === members.length && rotation.members.every((member) => members.some((current) => current.member_id === member.member_id && current.version === member.source_membership_version)), true);
    check(new Set(rotation.members.map((member) => member.member_id)).size === rotation.members.length);
    check(rotation.cards.length <= 2000 && new Set(rotation.cards.map((card) => card.card_id)).size === rotation.cards.length);
  }
  private async fresh(): Promise<S["VaultStatusResponse"]> {
    const expected = this.current().status;
    const current = await this.api.status(this.signal); this.validateStatus(current); this.life.assert();
    check(current.id === expected.id && current.version === expected.version && current.current_key_version === expected.current_key_version && current.own_membership === expected.own_membership, true);
    return current;
  }
  private async unlock(password: Bytes, rotation?: S["VaultRotationResponse"]) {
    const scope = this.scope();
    const result = rotation ? await this.api.stagedOwn(rotation.id, this.signal) : await this.api.own(this.signal);
    this.life.assert();
    check(result.wrapping.household_id === scope.householdId && result.wrapping.member_id === this.me.member_id && result.key_check.household_id === scope.householdId);
    const target = { ...scope, keyVersion: rotation?.key_version ?? scope.keyVersion };
    // ownKey destroys a key that finishes deriving after the view has already closed.
    const key = this.life.ownKey(await unwrapMember(password, target, this.me.member_id, result.wrapping, result.key_check));
    this.life.assert(); return { key, wrapping: result.wrapping };
  }
  private async mutate<T>(operation: () => Promise<T>): Promise<T> {
    this.life.assert(); this.#retry = operation;
    try { const result = await operation(); this.life.assert(); this.#retry = null; return result; }
    catch (error) { if (error instanceof ApiError && error.status > 0 && error.status < 500 && error.status !== 408 && !needsReauthentication(error)) this.#retry = null; throw error; }
  }
  private async refreshRotation(): Promise<boolean> {
    const previous = this.current(), status = await this.api.status(this.signal);
    this.validateStatus(status); this.life.assert();
    check(status.id === previous.status.id && status.own_membership === "active", true);
    if (!status.pending_rotation_id) return false;
    check(!previous.rotation || status.pending_rotation_id === previous.rotation.id, true);
    const rotation = await this.api.rotation(status.pending_rotation_id, this.signal);
    check(rotation.id === status.pending_rotation_id); this.checkRotation(rotation, status);
    this.life.assert(); this.context = { ...previous, status, rotation }; return true;
  }
  async reauthenticate(password: string): Promise<void> {
    this.life.clearSecrets(); this.life.beginStep();
    const member = await this.api.reauthenticate(password, this.signal); this.life.assert();
    check(member.household_id === this.me.household_id && member.member_id === this.me.member_id && member.user_id === this.me.user_id);
    if (["rotate", "resume-rotation"].includes(this.request.action)) {
      // A pending opaque retry must be resolved before deciding whether finalization completed.
      if (!await this.refreshRotation()) check(this.#retry || !this.context?.rotation, true);
    } else await this.fresh();
    this.life.waitForInput();
  }
  async retry(): Promise<"completed" | "rotation-pending"> {
    this.life.beginStep(); const operation = this.#retry; check(operation);
    await this.mutate(operation); this.life.clearSecrets();
    if (["rotate", "resume-rotation"].includes(this.request.action) && await this.refreshRotation()) {
      this.life.waitForInput(); return "rotation-pending";
    }
    return "completed";
  }
  async confirmRecovery(): Promise<void> {
    this.life.beginStep(); const operation = this.#prepared; check(operation); this.#prepared = null;
    this.life.clearDom();
    try { await operation(); } finally { this.life.clearSecrets(); }
  }
  private showRecovery(code: Bytes, operation: () => Promise<void>): WorkflowResult {
    this.life.assert(); this.recoveryOutput(encode64(code)); this.life.forgetBytes(code);
    this.life.waitForInput(); this.life.showFor30Seconds(async () => { await this.fresh(); });
    this.#prepared = operation; return "confirm-recovery";
  }
  private async checkedCard() {
    const initial = this.current().card; check(initial);
    const current = await this.api.cardMetadata(initial.id, this.signal); this.life.assert();
    check(current.id === initial.id && current.household_id === this.me.household_id);
    check(current.version === initial.version, true); return current;
  }
  async run(input: VaultInputs): Promise<WorkflowResult> {
    this.life.beginStep();
    const context = this.current(), r = this.request, status = await this.fresh();
    this.#prepared = null; this.#retry = null;
    if (r.action === "setup") {
      const scope = { householdId: this.me.household_id, keyVersion: 1 };
      const key = this.life.ownKey(VaultKey.generate()), code = this.life.ownBytes(randomBytes(32));
      const body: S["VaultInitialize"] = {
        key_check: await makeKeyCheck(key, scope),
        member_wrapping: await wrapMember(key, secret(input.newPasswords.get(this.me.member_id)), scope, this.me.member_id, 1),
        recovery_wrapping: await wrapRecovery(key, code, scope, 1),
      };
      this.life.forgetKey(key); const idempotency = crypto.randomUUID();
      return this.showRecovery(code, async () => { await this.mutate(() => this.api.initialize(body, idempotency, this.signal)); });
    }
    const scope = this.scope(status);
    if (r.action === "cancel-share") {
      const offer = context.offer; check(offer); const key = crypto.randomUUID();
      await this.mutate(() => this.api.cancelOffer(offer.id, offer.version, key, this.signal)); return "completed";
    }
    if (r.action === "revoke-member") {
      const member = status.members.find((member) => member.member_id === r.memberId);
      check(member?.status === "active" && member.version !== null && status.members.filter((m) => m.status === "active").length > 1, true);
      const key = crypto.randomUUID(); await this.mutate(() => this.api.revoke(r.memberId, member.version!, key, this.signal)); return "completed";
    }
    if (r.action === "abort-rotation") {
      check(context.rotation); const key = crypto.randomUUID();
      await this.mutate(() => this.api.abort(r.rotationId, context.rotation!.version, key, this.signal)); return "completed";
    }
    if (r.action === "purge") {
      const card = await this.checkedCard(); const key = crypto.randomUUID();
      await this.mutate(() => this.api.purge(card.id, card.version, key, this.signal)); return "completed";
    }
    if (r.action === "accept-share") {
      const response = await this.api.offer(r.offerId, this.signal); this.life.assert();
      check(response.offer.id === r.offerId && response.offer.version === context.offer?.version && response.offer.target_member_id === this.me.member_id && response.offer.household_id === this.me.household_id, true);
      check(response.wrapping.household_id === scope.householdId && response.key_check.household_id === scope.householdId);
      const key = this.life.ownKey(await unwrapMember(secret(input.password), scope, this.me.member_id, response.wrapping, response.key_check));
      this.life.assert(); this.life.forgetKey(key); const idempotency = crypto.randomUUID();
      await this.mutate(() => this.api.accept(r.offerId, { key_version: scope.keyVersion, key_check_confirmed: true }, response.offer.version, idempotency, this.signal)); return "completed";
    }
    if (r.action === "recover") {
      const response = await this.api.recovery(this.signal); this.life.assert();
      check(response.wrapping.household_id === scope.householdId && response.key_check.household_id === scope.householdId);
      const key = this.life.ownKey(await unwrapRecovery(secret(input.recoveryCode), scope, response.wrapping, response.key_check));
      const code = this.life.ownBytes(randomBytes(32));
      const own = status.members.find((member) => member.member_id === this.me.member_id); check(own?.status === "active");
      const body: S["VaultRecover"] = {
        member_wrapping: await wrapMember(key, secret(input.newPasswords.get(this.me.member_id)), scope, this.me.member_id, own.next_wrapping_generation),
        recovery_wrapping: await wrapRecovery(key, code, scope, advance(response.wrapping.generation)), key_check_confirmed: true,
      };
      this.life.forgetKey(key); const idempotency = crypto.randomUUID();
      return this.showRecovery(code, async () => { await this.mutate(() => this.api.recover(body, status.version!, idempotency, this.signal)); });
    }
    const unlocked = await this.unlock(secret(input.password));
    await this.fresh();
    if (r.action === "view") {
      const card = await this.checkedCard(), envelope = await this.api.card(card.id, this.signal);
      check(envelope.household_id === scope.householdId && envelope.card_id === card.id && envelope.card_version === card.version && envelope.last_four === card.last_four, true);
      const plain = this.life.ownBytes(await decryptCard(unlocked.key, scope, card.id, envelope));
      await this.fresh(); await this.checkedCard(); this.life.assert();
      this.cardOutput(displayCard(plain)); this.life.forgetBytes(plain); this.life.forgetKey(unlocked.key);
      this.life.showFor30Seconds(async () => { await this.fresh(); await this.checkedCard(); }); return "displayed";
    }
    if (r.action === "edit") {
      const card = await this.checkedCard();
      const body = await encryptCard(unlocked.key, scope, card.id, secret(input.card)); this.life.assert();
      const idempotency = crypto.randomUUID(); await this.mutate(() => this.api.saveCard(card.id, body, card.version, idempotency, this.signal)); return "completed";
    }
    if (r.action === "change-password") {
      const own = status.members.find((member) => member.member_id === this.me.member_id); check(own);
      const body: S["VaultMemberRewrap"] = { wrapping: await wrapMember(unlocked.key, secret(input.newPasswords.get(this.me.member_id)), scope, this.me.member_id, own.next_wrapping_generation), key_check_confirmed: true };
      const idempotency = crypto.randomUUID(); await this.mutate(() => this.api.rewrap(body, unlocked.wrapping.version, idempotency, this.signal)); return "completed";
    }
    if (r.action === "share") {
      const target = status.members.find((member) => member.member_id === r.memberId); check(target && target.member_id !== this.me.member_id && target.status !== "active", true);
      const body: S["VaultShareCreate"] = { wrapping: await wrapMember(unlocked.key, secret(input.newPasswords.get(r.memberId)), scope, r.memberId, target.next_wrapping_generation) };
      const idempotency = crypto.randomUUID(); await this.mutate(() => this.api.share(body, status.version!, idempotency, this.signal)); return "completed";
    }
    check(r.action === "rotate" || r.action === "resume-rotation");
    let rotation = context.rotation;
    if (r.action === "rotate" && !rotation) {
      const idempotency = crypto.randomUUID();
      const reference = await this.mutate(() => this.api.startRotation(input.reason, status.version!, idempotency, this.signal));
      rotation = await this.api.rotation(reference.id, this.signal);
      check(rotation.id === reference.id);
      const now = await this.api.status(this.signal); this.validateStatus(now); this.checkRotation(rotation, now);
      check(now.current_key_version === scope.keyVersion && now.own_membership === "active");
      this.context = { ...context, status: now, rotation };
    }
    check(rotation); this.life.assert();
    const nextScope = { ...scope, keyVersion: rotation.key_version };
    if (rotation.key_check_prepared) {
      check(rotation.recovery_prepared && rotation.members.every((member) => member.prepared));
      const next = await this.unlock(secret(input.stagedPassword), rotation);
      await this.migrateCards(rotation, unlocked.key, next.key); return "completed";
    }
    check(!rotation.recovery_prepared && rotation.members.every((member) => !member.prepared) && rotation.cards.every((card) => !card.prepared));
    const nextKey = this.life.ownKey(VaultKey.generate()), code = this.life.ownBytes(randomBytes(32));
    const members: S["MemberWrappingInput"][] = [];
    for (const member of rotation.members) {
      members.push(await wrapMember(nextKey, secret(input.newPasswords.get(member.member_id)), nextScope, member.member_id, 1)); this.life.assert();
    }
    const body: S["VaultRotationPrepare"] = { key_check: await makeKeyCheck(nextKey, nextScope), member_wrappings: members, recovery_wrapping: await wrapRecovery(nextKey, code, nextScope, 1) };
    const idempotency = crypto.randomUUID(), target = rotation;
    return this.showRecovery(code, async () => {
      await this.mutate(() => this.api.prepare(target.id, body, target.version, idempotency, this.signal));
      const prepared = await this.api.rotation(target.id, this.signal);
      await this.migrateCards(prepared, unlocked.key, nextKey);
    });
  }
  private rotationBinding(rotation: S["VaultRotationResponse"]): string {
    return JSON.stringify({ household: rotation.household_id, id: rotation.id, source: rotation.source_key_version, target: rotation.key_version,
      members: rotation.members.map(({ member_id, source_membership_version }) => ({ member_id, source_membership_version })).sort((a, b) => a.member_id.localeCompare(b.member_id)),
      cards: rotation.cards.map(({ card_id, source_envelope_id, source_revision, last_four }) => ({ card_id, source_envelope_id, source_revision, last_four })).sort((a, b) => a.card_id.localeCompare(b.card_id)) });
  }
  private async migrateCards(rotation: S["VaultRotationResponse"], oldKey: VaultKey, newKey: VaultKey) {
    const oldScope = this.scope(), nextScope = { ...oldScope, keyVersion: rotation.key_version };
    const current = await this.api.status(this.signal); this.validateStatus(current); this.checkRotation(rotation, current);
    check(current.own_membership === "active" && rotation.key_check_prepared && rotation.recovery_prepared && rotation.members.every((member) => member.prepared));
    const binding = this.rotationBinding(rotation), oldDigest = await oldKey.fingerprint(), newDigest = await newKey.fingerprint();
    this.life.assert();
    if (this.#cursor) check(this.#cursor.binding === binding && this.#cursor.oldKey === oldDigest && this.#cursor.newKey === newDigest, true);
    else this.#cursor = { binding, oldKey: oldDigest, newKey: newDigest, verified: new Set() };
    const cursor = this.#cursor;
    check([...cursor.verified].every((id) => rotation.cards.some((card) => card.card_id === id && card.prepared)), true);
    this.context = { ...this.current(), status: current, rotation };
    for (const target of rotation.cards) {
      if (cursor.verified.has(target.card_id)) continue;
      // A rotation advances across bounded foreground steps. A large prepared prefix
      // must not consume one fixed timeout on every resume and starve the suffix.
      this.life.beginStep();
      const source = await this.api.card(target.card_id, this.signal);
      check(source.household_id === oldScope.householdId && source.card_id === target.card_id && source.id === target.source_envelope_id && source.revision === target.source_revision && source.last_four === target.last_four, true);
      const plain = this.life.ownBytes(await decryptCard(oldKey, oldScope, target.card_id, source));
      try {
        if (!target.prepared) {
          const body: S["VaultRotationCardWrite"] = { source_envelope_id: target.source_envelope_id, source_revision: target.source_revision, envelope: await encryptCard(newKey, nextScope, target.card_id, plain) };
          const key = crypto.randomUUID();
          const reference = await this.mutate(() => this.api.stage(rotation.id, target.card_id, body, rotation.version, key, this.signal));
          rotation = { ...rotation, version: reference.version };
        }
        const staged = await this.api.stagedCard(rotation.id, target.card_id, this.signal);
        check(staged.household_id === nextScope.householdId && staged.card_id === target.card_id && staged.last_four === target.last_four);
        const verified = this.life.ownBytes(await decryptCard(newKey, nextScope, target.card_id, staged));
        try { check(verified.length === plain.length && verified.every((byte, index) => byte === plain[index])); }
        finally { this.life.forgetBytes(verified); }
        this.life.assert(); cursor.verified.add(target.card_id);
        this.context = { ...this.current(), rotation };
      } finally { this.life.forgetBytes(plain); }
    }
    this.life.beginStep();
    const final = await this.api.rotation(rotation.id, this.signal);
    const latest = await this.api.status(this.signal); this.validateStatus(latest); this.checkRotation(final, latest);
    check(final.id === rotation.id && final.key_version === rotation.key_version && final.version === rotation.version && final.cards.length === rotation.cards.length && final.cards.every((card) => card.prepared && rotation.cards.some((original) => original.card_id === card.card_id && original.source_envelope_id === card.source_envelope_id && original.source_revision === card.source_revision && original.last_four === card.last_four)), true);
    check(this.rotationBinding(final) === binding && cursor.verified.size === final.cards.length, true);
    const key = crypto.randomUUID();
    await this.mutate(() => this.api.finalize(final.id, { key_version: final.key_version, key_check_confirmed: true }, final.version, key, this.signal));
  }
}

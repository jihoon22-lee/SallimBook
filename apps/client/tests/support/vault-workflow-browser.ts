import { ApiError } from "../../src/platform/api";
import { VaultLifetime } from "../../src/features/vault/lifetime";
import { VaultWorkflow } from "../../src/features/vault/workflow";
import type { PrivateVaultApi } from "../../src/features/vault/privateApi";
import {
  VaultKey,
  cardPayload,
  decryptCard,
  encryptCard,
  makeKeyCheck,
  passwordBytes,
  unwrapMember,
  wrapMember,
} from "../../src/features/vault/crypto";
const id = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const passwordText = "Synthetic vault password 2026!";
const newPasswordText = "Synthetic new vault password 2026!";

export async function rotationScenario(mode: "reauth" | "retry" | "manifest" | "key") {
  const me = { user_id: id(1), member_id: id(2), household_id: id(3), display_name: "합성 사용자" };
  const scope = { householdId: me.household_id, keyVersion: 1 },
    nextScope = { ...scope, keyVersion: 2 };
  const oldKey = VaultKey.generate(),
    nextKey = VaultKey.generate();
  const oldPassword = passwordBytes(passwordText),
    newPassword = passwordBytes(newPasswordText);
  const oldCheck = { ...(await makeKeyCheck(oldKey, scope)), household_id: me.household_id };
  let nextCheck = { ...(await makeKeyCheck(nextKey, nextScope)), household_id: me.household_id };
  const own = {
    ...(await wrapMember(oldKey, oldPassword, scope, me.member_id, 1)),
    household_id: me.household_id,
    version: 1,
  };
  let nextOwn = {
    ...(await wrapMember(nextKey, newPassword, nextScope, me.member_id, 1)),
    household_id: me.household_id,
    version: 1,
  };
  const cards = Array.from({ length: 6 }, (_, index) => ({
    card_id: id(50 + index),
    source_envelope_id: id(150 + index),
    source_revision: 1,
    last_four: "4242",
    prepared: index === 0,
  }));
  const rotation = {
    household_id: me.household_id,
    id: id(801),
    source_key_version: 1,
    key_version: 2,
    state: "staging",
    version: 1,
    key_check_prepared: true,
    recovery_prepared: true,
    members: [{ member_id: me.member_id, source_membership_version: 1, prepared: true }],
    cards,
  };
  const status = {
    household_id: me.household_id,
    id: id(800),
    initialized: true,
    version: 2,
    current_key_version: 1,
    own_membership: "active",
    members: [{ member_id: me.member_id, status: "active", version: 1 }],
    pending_rotation_id: rotation.id,
  };
  const codes = [undefined, "", "007", "0009", "123", ""] as const;
  const expected = new Map<string, number[]>();
  const sources = new Map<string, any>(),
    staged = new Map<string, any>();
  for (const [index, card] of cards.entries()) {
    const plain = cardPayload("4242424242424242", 2032, 12, codes[index]);
    expected.set(card.card_id, Array.from(plain));
    sources.set(card.card_id, {
      ...(await encryptCard(oldKey, scope, card.card_id, plain)),
      household_id: me.household_id,
      card_id: card.card_id,
      id: card.source_envelope_id,
      revision: 1,
    });
    if (card.prepared)
      staged.set(card.card_id, {
        ...(await encryptCard(nextKey, nextScope, card.card_id, plain)),
        household_id: me.household_id,
        card_id: card.card_id,
      });
    plain.fill(0);
  }
  oldKey.destroy();
  nextKey.destroy();
  oldPassword.fill(0);
  newPassword.fill(0);
  let allowance = mode === "reauth" ? 2 : 6,
    reauthCount = 0,
    finalized = 0,
    lost = false,
    retryIdentical = true;
  let lastCommand = "",
    snapshotError = false;
  const reads: string[] = [],
    writes: string[] = [];
  const api = {
    status: async () => structuredClone(status),
    members: async () => [me],
    rotation: async () => structuredClone(rotation),
    own: async () => ({ wrapping: own, key_check: oldCheck }),
    stagedOwn: async () => ({ wrapping: nextOwn, key_check: nextCheck }),
    card: async (cardId: string) => {
      if (!allowance) throw new ApiError(403, "REAUTHENTICATION_REQUIRED");
      allowance--;
      reads.push(cardId);
      return sources.get(cardId);
    },
    stagedCard: async (_rotationId: string, cardId: string) => staged.get(cardId),
    stage: async (_rotationId: string, cardId: string, body: any, version: number, key: string) => {
      const command = JSON.stringify({ cardId, body, version, key });
      if (lastCommand) {
        retryIdentical &&= lastCommand === command;
        lastCommand = "";
        return { version: rotation.version };
      }
      if (version !== rotation.version) throw new ApiError(409, "VERSION_CONFLICT");
      staged.set(cardId, { ...body.envelope, household_id: me.household_id, card_id: cardId });
      cards.find((card) => card.card_id === cardId)!.prepared = true;
      rotation.version++;
      writes.push(cardId);
      if (mode === "retry" && !lost) {
        lost = true;
        lastCommand = command;
        throw new ApiError(408, "REQUEST_FAILED");
      }
      if (["manifest", "key"].includes(mode) && writes.length === 1) {
        allowance = 0;
      }
      return { version: rotation.version };
    },
    finalize: async (_id: string, _body: unknown, version: number) => {
      if (version !== rotation.version || !cards.every((card) => card.prepared))
        throw new ApiError(409, "VERSION_CONFLICT");
      finalized++;
      status.current_key_version = 2;
      status.pending_rotation_id = null as any;
      status.version++;
      return { version: rotation.version + 1 };
    },
    reauthenticate: async () => {
      reauthCount++;
      allowance = 2;
      return me;
    },
  } as unknown as PrivateVaultApi;
  const root = document.createElement("section");
  document.body.append(root);
  const life = new VaultLifetime(root, () => {}),
    work = new VaultWorkflow(
      api,
      me as any,
      { action: "resume-rotation", rotationId: rotation.id },
      life,
      () => {},
      () => {},
    );
  await work.load();
  let retryResult = "";
  try {
    for (let attempt = 0; attempt < 8 && !finalized; attempt++) {
      try {
        await work.run({
          password: life.ownBytes(passwordBytes(passwordText)),
          stagedPassword: life.ownBytes(passwordBytes(newPasswordText)),
          newPasswords: new Map(),
          reason: "routine",
        });
      } catch (error) {
        life.clearSecrets();
        if (mode === "retry" && work.canRetry) {
          retryResult = await work.retry();
          continue;
        }
        if (error instanceof ApiError && error.code === "REAUTHENTICATION_REQUIRED") {
          if (mode === "manifest") cards[0]!.source_revision++;
          if (mode === "key") {
            const substitute = VaultKey.generate(),
              pw = passwordBytes(newPasswordText);
            nextCheck = {
              ...(await makeKeyCheck(substitute, nextScope)),
              household_id: me.household_id,
            };
            nextOwn = {
              ...(await wrapMember(substitute, pw, nextScope, me.member_id, 1)),
              household_id: me.household_id,
              version: 1,
            };
            substitute.destroy();
            pw.fill(0);
          }
          await work.reauthenticate("Synthetic account password 2026!");
          continue;
        }
        if (error instanceof ApiError && error.status === 409) {
          snapshotError = true;
          break;
        }
        throw error;
      } finally {
        life.clearSecrets();
      }
    }
    const verifyPassword = passwordBytes(newPasswordText),
      verifyKey = await unwrapMember(verifyPassword, nextScope, me.member_id, nextOwn, nextCheck);
    let valid = true;
    if (finalized)
      for (const card of cards) {
        const bytes = await decryptCard(
          verifyKey,
          nextScope,
          card.card_id,
          staged.get(card.card_id),
        );
        valid &&= JSON.stringify(Array.from(bytes)) === JSON.stringify(expected.get(card.card_id));
        bytes.fill(0);
      }
    verifyPassword.fill(0);
    verifyKey.destroy();
    return {
      reads,
      writes,
      finalized,
      reauthCount,
      retryResult,
      retryIdentical,
      snapshotError,
      valid,
    };
  } finally {
    life.close();
    work.dispose();
    root.remove();
  }
}

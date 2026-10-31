import { expect, test } from "@playwright/test";
import v2 from "../../../packages/test-fixtures/vault-v2.json" with { type: "json" };
import vector from "../../../packages/test-fixtures/vault-v1.json" with { type: "json" };

test.use({ trace: "off", screenshot: "off", video: "off" });

test.beforeEach(async ({ page }) => {
  await page.route("**/api/v1/**", (route) =>
    route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({ error: { code: "UNAUTHENTICATED", message: "synthetic" } }),
    }),
  );
  await page.goto("/");
});

test("WebCrypto matches independent Python v2 ciphertext for empty and zero-prefixed CVC", async ({
  page,
}) => {
  const result = await page.evaluate(async (fixture) => {
    const c = await import("/src/features/vault/crypto.ts");
    const hex = (s: string) => new Uint8Array(s.match(/../g)!.map((v) => parseInt(v, 16)));
    const key = await crypto.subtle.importKey("raw", hex(fixture.hvk_hex), "AES-GCM", false, [
      "encrypt",
    ]);
    const values = [];
    for (const row of fixture.cards) {
      const plain = c.cardPayload(fixture.pan, fixture.expiry_year, fixture.expiry_month, row.cvc);
      const aad = c.cardAad(
        { householdId: fixture.household_id, keyVersion: fixture.key_version },
        fixture.card_id,
        2,
      );
      const cipher = new Uint8Array(
        await crypto.subtle.encrypt(
          { name: "AES-GCM", iv: c.decode64(row.nonce, 12), additionalData: aad, tagLength: 128 },
          key,
          plain,
        ),
      );
      values.push({ payload: [...plain], aad: [...aad], cipher: c.encode64(cipher) });
      c.wipe(plain);
    }
    return values;
  }, v2);
  result.forEach((row, index) => {
    expect(row.payload).toEqual([...Buffer.from(v2.cards[index]!.payload_hex, "hex")]);
    expect(row.aad).toEqual([...Buffer.from(v2.cards[index]!.aad_hex, "hex")]);
    expect(row.cipher).toBe(v2.cards[index]!.ciphertext);
  });
});

test("v2 CVC remains encrypted, schema bound and roundtrips zero-prefixed codes", async ({
  page,
}) => {
  const result = await page.evaluate(async () => {
    const c = await import("/src/features/vault/crypto.ts");
    const scope = { householdId: "00000000-0000-4000-8000-000000000003", keyVersion: 1 };
    const card = "00000000-0000-4000-8000-000000000004";
    const key = c.VaultKey.generate();
    const rows = [];
    let rejected = 0;
    try {
      for (const code of ["", "007", "0009"]) {
        const plain = c.cardPayload("4242424242424242", 2030, 12, code);
        const sealed = await c.encryptCard(key, scope, card, plain);
        const opened = await c.decryptCard(key, scope, card, sealed);
        rows.push({
          size: plain.length,
          schema: sealed.payload_schema_version,
          cipherSize: c.decode64(sealed.ciphertext, 48).length,
          equal: plain.every((v, i) => v === opened[i]),
          shown: c.displayCard(opened).includes(code || "CVC 미입력"),
        });
        try {
          await c.decryptCard(key, scope, card, { ...sealed, payload_schema_version: 1 });
        } catch {
          rejected++;
        }
        c.wipe(plain);
        c.wipe(opened);
      }
      for (const invalid of ["1", "12", "12345", "a12", "１２３"]) {
        try {
          c.cardPayload("4242424242424242", 2030, 12, invalid);
        } catch {
          rejected++;
        }
      }
    } finally {
      key.destroy();
    }
    return { rows, rejected };
  });
  expect(result.rows).toEqual(
    Array(3).fill({ size: 32, schema: 2, cipherSize: 48, equal: true, shown: true }),
  );
  expect(result.rejected).toBe(8);
});

test("WebCrypto matches public Python/Android vectors, original Unicode bytes and every AAD", async ({
  page,
}) => {
  const result = await page.evaluate(async (fixture) => {
    const c = await import("/src/features/vault/crypto.ts");
    const hex = (bytes: Uint8Array) =>
      [...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("");
    const scope = { householdId: fixture.household_id, keyVersion: fixture.key_version };
    const check = { format_version: 1, key_version: fixture.key_version, ...fixture.key_check };
    const envelope = {
      format_version: 1,
      key_version: fixture.key_version,
      payload_schema_version: 1,
      last_four: "4242",
      ...fixture.card,
    };
    const proofs = [];
    for (const row of fixture.members) {
      const password = c.passwordBytes(row.password);
      const wrap = {
        format_version: 1,
        key_version: fixture.key_version,
        kdf: "PBKDF2-HMAC-SHA256",
        ...row,
      };
      const key = await c.unwrapMember(password, scope, row.member_id, wrap, check);
      const plain = await c.decryptCard(key, scope, fixture.card.card_id, envelope);
      proofs.push({
        password: hex(password),
        aad: hex(
          c.memberAad(
            scope,
            row.member_id,
            row.generation,
            row.iterations,
            c.decode64(row.salt, 16),
          ),
        ),
        plain: hex(plain),
        cipher: c.encode64(
          await key.encrypt(
            c.decode64(fixture.card.nonce, 12),
            c.cardAad(scope, fixture.card.card_id),
            plain,
          ),
        ),
      });
      c.wipe(password);
      c.wipe(plain);
      key.destroy();
    }
    const recovery = {
      format_version: 1,
      key_version: fixture.key_version,
      kdf: "HKDF-SHA256",
      ...fixture.recovery,
    };
    const code = c.decode64(fixture.recovery.code, 32);
    const key = await c.unwrapRecovery(code, scope, recovery, check);
    const plain = await c.decryptCard(key, scope, fixture.card.card_id, envelope);
    const output = {
      proofs,
      recoveryPlain: hex(plain),
      cardAad: hex(c.cardAad(scope, fixture.card.card_id)),
      recoveryAad: hex(c.recoveryAad(scope, recovery.generation, c.decode64(recovery.salt, 16))),
      checkAad: hex(c.checkAad(scope)),
    };
    c.wipe(plain);
    c.wipe(code);
    key.destroy();
    return output;
  }, vector);
  expect(result.proofs).toEqual(
    vector.members.map((row) => ({
      password: row.password_utf8_hex,
      aad: row.aad_hex,
      plain: vector.card.payload_hex,
      cipher: vector.card.ciphertext,
    })),
  );
  expect(result.recoveryPlain).toBe(vector.card.payload_hex);
  expect(result.cardAad).toBe(vector.card.aad_hex);
  expect(result.recoveryAad).toBe(vector.recovery.aad_hex);
  expect(result.checkAad).toBe(vector.key_check.aad_hex);
});

test("fresh client keys and independent wrappers decrypt without sharing passwords or plaintext", async ({
  page,
}) => {
  expect(
    await page.evaluate(async (fixture) => {
      const c = await import("/src/features/vault/crypto.ts");
      const scope = { householdId: fixture.household_id, keyVersion: 1 };
      const key = c.VaultKey.generate(),
        password = c.passwordBytes(fixture.members[0].password, true),
        code = c.randomBytes(32);
      const check = await c.makeKeyCheck(key, scope);
      const first = await c.wrapMember(key, password, scope, fixture.members[0].member_id, 1);
      const second = await c.wrapMember(key, password, scope, fixture.members[0].member_id, 2);
      const recovery = await c.wrapRecovery(key, code, scope, 1);
      const plain = c.cardPayload(
        fixture.card.pan,
        fixture.card.expiry_year,
        fixture.card.expiry_month,
      );
      const envelope = await c.encryptCard(key, scope, fixture.card.card_id, plain);
      key.destroy();
      const fromMember = await c.unwrapMember(
        password,
        scope,
        fixture.members[0].member_id,
        first,
        check,
      );
      const fromCode = await c.unwrapRecovery(code, scope, recovery, check);
      const memberPlain = await c.decryptCard(fromMember, scope, fixture.card.card_id, envelope);
      const recoveryPlain = await c.decryptCard(fromCode, scope, fixture.card.card_id, envelope);
      const ok =
        c.displayCard(memberPlain) === `${fixture.card.pan} · 2032/12` &&
        memberPlain.every((byte, i) => byte === recoveryPlain[i]) &&
        first.nonce !== second.nonce &&
        first.salt !== second.salt &&
        envelope.last_four === "4242";
      [plain, memberPlain, recoveryPlain, password, code].forEach(c.wipe);
      fromMember.destroy();
      fromCode.destroy();
      return ok && !plain.some(Boolean) && !password.some(Boolean) && !code.some(Boolean);
    }, vector),
  ).toBe(true);
});

test("wrong credentials, scope, tag, metadata and format fail closed", async ({ page }) => {
  const rejected = await page.evaluate(async (fixture) => {
    const c = await import("/src/features/vault/crypto.ts");
    const scope = { householdId: fixture.household_id, keyVersion: fixture.key_version },
      row = fixture.members[0];
    const wrap = {
      format_version: 1,
      key_version: fixture.key_version,
      kdf: "PBKDF2-HMAC-SHA256",
      ...row,
    };
    const check = { format_version: 1, key_version: fixture.key_version, ...fixture.key_check };
    const password = c.passwordBytes(row.password),
      badPassword = c.passwordBytes(row.password.trim());
    const key = await c.unwrapMember(password, scope, row.member_id, wrap, check);
    const envelope = {
      format_version: 1,
      key_version: fixture.key_version,
      payload_schema_version: 1,
      last_four: "4242",
      ...fixture.card,
    };
    const corrupted = c.decode64(envelope.ciphertext, 43);
    corrupted[42] ^= 1;
    const cases = [
      () => c.unwrapMember(badPassword, scope, row.member_id, wrap, check),
      () =>
        c.unwrapMember(
          password,
          { ...scope, householdId: fixture.card.card_id },
          row.member_id,
          wrap,
          check,
        ),
      () => c.unwrapMember(password, scope, fixture.members[1].member_id, wrap, check),
      () =>
        c.unwrapMember(password, scope, row.member_id, { ...wrap, iterations: 2_000_001 }, check),
      () => c.unwrapMember(password, scope, row.member_id, { ...wrap, kdf: "other" }, check),
      () => c.decryptCard(key, { ...scope, keyVersion: 8 }, fixture.card.card_id, envelope),
      () => c.decryptCard(key, scope, fixture.household_id, envelope),
      () =>
        c.decryptCard(key, scope, fixture.card.card_id, {
          ...envelope,
          ciphertext: c.encode64(corrupted),
        }),
      () => c.decryptCard(key, scope, fixture.card.card_id, { ...envelope, last_four: "0000" }),
      () =>
        c.decryptCard(key, scope, fixture.card.card_id, { ...envelope, payload_schema_version: 2 }),
      () =>
        c.decryptCard(key, scope, fixture.card.card_id, {
          ...envelope,
          nonce: envelope.nonce + "=",
        }),
    ];
    let count = 0;
    for (const work of cases) {
      try {
        await work();
      } catch (error) {
        if (error instanceof c.VaultCryptoError) count++;
      }
    }
    key.destroy();
    try {
      await c.decryptCard(key, scope, fixture.card.card_id, envelope);
    } catch (error) {
      if (error instanceof c.VaultCryptoError) count++;
    }
    c.wipe(password);
    c.wipe(badPassword);
    return count;
  }, vector);
  expect(rejected).toBe(12);
});

test("input bounds reject malformed Unicode, lossy encodings and invalid payloads", async ({
  page,
}) => {
  expect(
    await page.evaluate(async () => {
      const c = await import("/src/features/vault/crypto.ts");
      const cases = [
        () => c.passwordBytes("short", true),
        () => c.passwordBytes("\ud800"),
        () => c.passwordBytes("\udc00"),
        () => c.passwordBytes("한".repeat(342)),
        () => c.passwordBytes(""),
        () => c.decode64("AB", 1),
        () => c.decode64("AA=", 1),
        () => c.cardPayload("4242424242424243", 2032, 12),
        () => c.cardPayload("4242 4242 4242 4242", 2032, 12),
        () => c.cardPayload("4242424242424242", 2200, 12),
        () => c.cardPayload("4242424242424242", 2032, 0),
        () => c.cardAad({ householdId: "not-a-uuid", keyVersion: 1 }, "not-a-uuid"),
        () =>
          c.checkAad({
            householdId: "00000000-0000-4000-8000-000000000001",
            keyVersion: Number.MAX_SAFE_INTEGER + 1,
          }),
      ];
      let count = 0;
      for (const work of cases) {
        try {
          work();
        } catch (error) {
          if (error instanceof c.VaultCryptoError) count++;
        }
      }
      return count;
    }),
  ).toBe(13);
});

test("all-zero PANs fail input encryption and decryption consistently with Android", async ({
  page,
}) => {
  const rejected = await page.evaluate(async (fixture) => {
    const c = await import("/src/features/vault/crypto.ts");
    const key = c.VaultKey.generate(),
      scope = { householdId: fixture.household_id, keyVersion: 1 };
    let count = 0;
    try {
      for (let length = 13; length <= 19; length++) {
        const plain = new Uint8Array(27);
        plain.set([83, 66, 86, 49, length]);
        plain.fill(48, 5, 5 + length);
        new DataView(plain.buffer).setUint16(24, 2032, false);
        plain[26] = 12;
        const nonce = c.randomBytes(12);
        const ciphertext = await key.encrypt(nonce, c.cardAad(scope, fixture.card.card_id), plain);
        const cases = [
          () => c.cardPayload("0".repeat(length), 2032, 12),
          () => c.encryptCard(key, scope, fixture.card.card_id, plain),
          () =>
            c.decryptCard(key, scope, fixture.card.card_id, {
              format_version: 1,
              key_version: 1,
              payload_schema_version: 1,
              last_four: "0000",
              nonce: c.encode64(nonce),
              ciphertext: c.encode64(ciphertext),
            }),
        ];
        try {
          for (const operation of cases) {
            try {
              await operation();
            } catch (error) {
              if (error instanceof c.VaultCryptoError) count++;
            }
          }
        } finally {
          c.wipe(plain);
          c.wipe(nonce);
          c.wipe(ciphertext);
        }
      }
    } finally {
      key.destroy();
    }
    return count;
  }, vector);
  expect(rejected).toBe(21);
});

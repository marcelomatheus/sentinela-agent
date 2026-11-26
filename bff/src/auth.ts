import { createHash, createHmac, randomBytes } from "node:crypto";
import { EncryptJWT, jwtDecrypt } from "jose";
import { z } from "zod";

export const Identity = z.object({
  kind: z.literal("session"),
  principal: z.string().regex(/^[a-f0-9]{64}$/),
  name: z.string().max(100),
  csrf: z.string().length(48),
});

export type Identity = z.infer<typeof Identity>;

export const LoginAttempt = z.object({
  kind: z.literal("login"),
  state: z.string().min(10),
  verifier: z.string().min(30),
  nonce: z.string().min(10),
});

export function require32Bytes(secret: string): Uint8Array {
  const key = Buffer.from(secret, "base64url");
  if (key.length !== 32) throw new Error("BFF_SESSION_KEY must be 32 random bytes in base64url");
  return key;
}

export async function seal(
  payload: Record<string, unknown>,
  key: Uint8Array,
  seconds: number,
): Promise<string> {
  return new EncryptJWT(payload)
    .setProtectedHeader({ alg: "dir", enc: "A256GCM" })
    .setIssuedAt()
    .setExpirationTime(Math.floor(Date.now() / 1000) + seconds)
    .encrypt(key);
}

export async function unseal(token: string, key: Uint8Array): Promise<unknown> {
  const { payload } = await jwtDecrypt(token, key, {
    keyManagementAlgorithms: ["dir"],
    contentEncryptionAlgorithms: ["A256GCM"],
  });
  return payload;
}

export function newCsrf(): string {
  return randomBytes(24).toString("hex");
}

export function principalOf(issuer: string, subject: string): string {
  return createHash("sha256").update(issuer + "\n" + subject).digest("hex");
}

export function internalHeaders(principal: string, secret: string, now = Math.floor(Date.now() / 1000)): Record<string, string> {
  const timestamp = String(now);
  const signature = createHmac("sha256", secret)
    .update(principal + "\n" + timestamp).digest("hex");
  return {
    "x-sentinela-principal": principal,
    "x-sentinela-timestamp": timestamp,
    "x-sentinela-signature": signature,
  };
}

export function validCsrf(identity: Identity, header: unknown): boolean {
  if (typeof header !== "string") return false;
  // String comparison is constant time for equal-sized tokens.
  const a = Buffer.from(identity.csrf, "utf8");
  const b = Buffer.from(header, "utf8");
  return a.length === b.length &&
    (awaitTimingSafeEqual(a, b));
}

import { timingSafeEqual } from "node:crypto";
function awaitTimingSafeEqual(a: Buffer, b: Buffer): boolean {
  return timingSafeEqual(a, b);
}

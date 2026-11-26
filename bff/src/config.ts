import { z } from "zod";

export const envSchema = z.object({
  NODE_ENV: z.enum(["development","test","production"]).default("production"),
  PORT: z.coerce.number().int().min(1).max(65535).default(3005),
  BFF_PUBLIC_URL: z.url(),
  OIDC_ISSUER: z.url(),
  OIDC_CLIENT_ID: z.string().min(1),
  OIDC_CLIENT_SECRET: z.string().default(""),
  BFF_SESSION_KEY: z.string().min(40),
  WEB_INTERNAL_KEY: z.string().min(32),
  SENTINELA_INTERNAL_URL: z.url().default("http://api:8080"),
  WEB_DIST: z.string().default("/app/web-dist"),
  BFF_ALLOW_HTTP: z.enum(["true","false"]).default("false"),
});

export type BffConfig = z.infer<typeof envSchema>;

export function readConfig(env: NodeJS.ProcessEnv = process.env): BffConfig {
  const result = envSchema.parse(env);
  if (result.BFF_ALLOW_HTTP !== "true" && !result.BFF_PUBLIC_URL.startsWith("https://")) {
    throw new Error("BFF_PUBLIC_URL must use HTTPS unless BFF_ALLOW_HTTP=true");
  }
  return result;
}

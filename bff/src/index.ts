import Fastify, { type FastifyReply, type FastifyRequest } from "fastify";
import cookie from "@fastify/cookie";
import helmet from "@fastify/helmet";
import rateLimit from "@fastify/rate-limit";
import multipart from "@fastify/multipart";
import fastifyStatic from "@fastify/static";
import * as oidc from "openid-client";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { once } from "node:events";
import { z } from "zod";

import { readConfig, type BffConfig } from "./config";
import {
  Identity, LoginAttempt, internalHeaders, newCsrf, principalOf,
  require32Bytes, seal, unseal, validCsrf,
} from "./auth";

const paramsSchema = z.object({ id: z.uuid() });
const messageInput = z.strictObject({
  clientMessageId: z.uuid(),
  kind: z.enum(["text","image","audio"]),
  text: z.string().max(4000).default(""),
  attachmentId: z.uuid().nullable().optional(),
}).superRefine((message, context) => {
  if (message.kind === "text" && (!message.text.trim() || message.attachmentId)) {
    context.addIssue({code:"custom",message:"invalid text",path:["text"]});
  }
  if (message.kind !== "text" && !message.attachmentId) {
    context.addIssue({code:"custom",message:"file required",path:["attachmentId"]});
  }
});

function error(statusCode: number, message: string): Error {
  return Object.assign(new Error(message), { statusCode });
}

export async function createBff(config: BffConfig = readConfig()) {
  const key = require32Bytes(config.BFF_SESSION_KEY);
  const app = Fastify({ logger: true, bodyLimit: 9000000, requestTimeout: 35000 });
  await app.register(cookie);
  await app.register(helmet, { global: true });
  await app.register(rateLimit, { global: false });
  await app.register(multipart, {
    limits: { files: 1, fileSize: 8000000, fields: 0 },
  });

  const provider = await oidc.discovery(
    new URL(config.OIDC_ISSUER), config.OIDC_CLIENT_ID,
    config.OIDC_CLIENT_SECRET || undefined,
  );
  const secure = config.BFF_ALLOW_HTTP !== "true";
  const sessionCookie = "sentinela_session";
  const loginCookie = "sentinela_oauth";

  async function identity(request: FastifyRequest): Promise<Identity> {
    const value = request.cookies[sessionCookie];
    if (!value) throw error(401, "authentication required");
    try {
      return Identity.parse(await unseal(value, key));
    } catch {
      throw error(401, "session expired");
    }
  }

  async function authorized(
    request: FastifyRequest, mutable = false,
  ): Promise<Identity> {
    const user = await identity(request);
    if (mutable && !validCsrf(user, request.headers["x-csrf-token"])) {
      throw error(403, "invalid CSRF token");
    }
    return user;
  }

  async function proxy(
    user: Identity, method: string, path: string,
    payload?: BodyInit, mime?: string, stream = false,
  ): Promise<Response> {
    const response = await fetch(
      new URL("/internal/web" + path, config.SENTINELA_INTERNAL_URL),
      {
        method,
        headers: {
          ...internalHeaders(user.principal, config.WEB_INTERNAL_KEY),
          ...(mime ? {"content-type":mime} : {}),
        },
        body: payload,
        signal: stream ? undefined : AbortSignal.timeout(30000),
        cache: "no-store",
      },
    );
    return response;
  }

  async function forward(reply: FastifyReply, upstream: Response): Promise<FastifyReply> {
    const value = await upstream.text();
    // Only backend JSON is reflected, never arbitrary upstream HTML.
    const isJson = upstream.headers.get("content-type")?.includes("application/json");
    reply.code(upstream.status);
    if (isJson) {
      try { return reply.send(JSON.parse(value) as unknown); }
      catch { throw error(502,"invalid upstream JSON"); }
    }
    if (upstream.status === 204) return reply.send();
    return reply.send({error:upstream.ok ? "unexpected response" : "service unavailable"});
  }

  app.get("/health/live", async () => ({status:"ok"}));

  app.get("/auth/login", async (_request, reply) => {
    const state=oidc.randomState();
    const verifier=oidc.randomPKCECodeVerifier();
    const nonce=oidc.randomNonce();
    const challenge=await oidc.calculatePKCECodeChallenge(verifier);
    const transaction=await seal({kind:"login",state,verifier,nonce},key,600);
    reply.setCookie(loginCookie,transaction,{
      path:"/auth/callback",httpOnly:true,secure,sameSite:"lax",maxAge:600,
    });
    const url=oidc.buildAuthorizationUrl(provider,{
      scope:"openid profile email",
      redirect_uri:new URL("/auth/callback",config.BFF_PUBLIC_URL).href,
      state,nonce,code_challenge:challenge,code_challenge_method:"S256",
    });
    return reply.redirect(url.href);
  });

  app.get("/auth/callback", async (request, reply) => {
    const raw=request.cookies[loginCookie];
    if (!raw) throw error(401,"login session unavailable");
    let transaction: z.infer<typeof LoginAttempt>;
    try { transaction=LoginAttempt.parse(await unseal(raw,key)); }
    catch { throw error(401,"login session expired"); }
    reply.clearCookie(loginCookie,{path:"/auth/callback"});
    const url=new URL(request.raw.url ?? "/auth/callback",config.BFF_PUBLIC_URL);
    const tokens=await oidc.authorizationCodeGrant(provider,url,{
      expectedState:transaction.state,
      expectedNonce:transaction.nonce,
      pkceCodeVerifier:transaction.verifier,
    });
    const claims=tokens.claims();
    if (!claims?.sub || !claims.iss) throw error(401,"invalid identity");
    const principal=principalOf(claims.iss,claims.sub);
    const name=typeof claims.name==="string" ? claims.name.slice(0,100) : "Você";
    const session=await seal({
      kind:"session",principal,name,csrf:newCsrf(),
    },key,8*60*60);
    reply.setCookie(sessionCookie,session,{
      path:"/",httpOnly:true,secure,sameSite:"lax",maxAge:8*60*60,
    });
    return reply.redirect("/app");
  });

  app.get("/api/session", async (request) => {
    try {
      const user=await identity(request);
      return {authenticated:true,name:user.name,csrf:user.csrf};
    } catch {
      return {authenticated:false};
    }
  });

  app.post("/auth/logout", async (request,reply) => {
    await authorized(request,true);
    reply.clearCookie(sessionCookie,{path:"/"});
    return reply.code(204).send();
  });

  app.get("/api/conversations", async (request,reply) =>
    forward(reply,await proxy(await authorized(request),"GET","/conversations"))
  );
  app.post("/api/conversations", async (request,reply) =>
    forward(reply,await proxy(await authorized(request,true),"POST","/conversations"))
  );
  app.get("/api/conversations/:id/messages", async (request,reply) => {
    const params=paramsSchema.parse(request.params);
    const query=z.object({before:z.iso.datetime({offset:true}).optional()}).parse(request.query);
    const suffix=query.before ? "?before="+encodeURIComponent(query.before) : "";
    return forward(reply,await proxy(
      await authorized(request),"GET",`/conversations/${params.id}/messages${suffix}`,
    ));
  });
  app.post("/api/conversations/:id/messages", async (request,reply) => {
    const params=paramsSchema.parse(request.params);
    const body=messageInput.parse(request.body);
    return forward(reply,await proxy(
      await authorized(request,true),"POST",`/conversations/${params.id}/messages`,
      JSON.stringify(body),"application/json",
    ));
  });
  app.post("/api/conversations/:id/attachments", {
    config:{rateLimit:{max:20,timeWindow:"1 minute"}},
  }, async (request,reply) => {
    const params=paramsSchema.parse(request.params);
    const user=await authorized(request,true);
    const attachment=await request.file();
    if (!attachment) throw error(400,"attachment required");
    const mime=attachment.mimetype.toLowerCase();
    if (!/^(image\/(jpeg|png|webp)|audio\/(ogg|webm|mpeg|wav))$/.test(mime)) {
      throw error(415,"unsupported MIME");
    }
    const content=await attachment.toBuffer();
    const max=mime.startsWith("image/") ? 8000000 : 1000000;
    if (!content.length || content.length>max) throw error(413,"file exceeds limit");
    return forward(reply,await proxy(
      user,"POST",`/conversations/${params.id}/attachments`,new Uint8Array(content),mime,
    ));
  });
  app.post("/api/conversations/:id/reset", async (request,reply) => {
    const params=paramsSchema.parse(request.params);
    return forward(reply,await proxy(
      await authorized(request,true),"POST",`/conversations/${params.id}/reset`,
    ));
  });
  app.delete("/api/conversations/:id", async (request,reply) => {
    const params=paramsSchema.parse(request.params);
    return forward(reply,await proxy(
      await authorized(request,true),"DELETE",`/conversations/${params.id}`,
    ));
  });

  app.get("/api/conversations/:id/events", async (request,reply) => {
    const params=paramsSchema.parse(request.params);
    const user=await authorized(request);
    const query=z.object({after:z.coerce.number().int().min(0).default(0)}).parse(request.query);
    const lastId=Number(request.headers["last-event-id"]??0);
    const after=Number.isSafeInteger(lastId)&&lastId>=0?Math.max(query.after,lastId):query.after;
    const upstream=await proxy(
      user,"GET",`/conversations/${params.id}/events?after=${after}`,
      undefined,undefined,true,
    );
    if (!upstream.ok || !upstream.body) return forward(reply,upstream);
    reply.hijack();
    reply.raw.writeHead(200,{
      "content-type":"text/event-stream; charset=utf-8",
      "cache-control":"no-store,no-transform",
      "x-accel-buffering":"no",
      "connection":"keep-alive",
    });
    const controller=new AbortController();
    reply.raw.on("close",()=>controller.abort());
    try {
      for await (const chunk of upstream.body) {
        if (controller.signal.aborted) break;
        if (!reply.raw.write(Buffer.from(chunk))) await once(reply.raw,"drain");
      }
    } catch {
      app.log.warn("SSE upstream disconnected");
    } finally {
      await upstream.body.cancel().catch(()=>undefined);
      reply.raw.end();
    }
  });

  app.setErrorHandler((cause, _request, reply) => {
    const failure=cause as Error & {statusCode?:number};
    const zodError=cause instanceof z.ZodError;
    const status=zodError ? 422 : (failure.statusCode ?? 500);
    if (status>=500) app.log.error({err:cause},"BFF request failed");
    return reply.code(status).send({
      error:status>=500 ? "service unavailable" : failure.message,
    });
  });

  if (existsSync(config.WEB_DIST)) {
    await app.register(fastifyStatic,{root:join(config.WEB_DIST,"assets"),prefix:"/assets/"});
    app.setNotFoundHandler((request,reply) => {
      if (request.method==="GET" && request.headers.accept?.includes("text/html")) {
        return reply.type("text/html").sendFile("index.html",config.WEB_DIST);
      }
      return reply.code(404).send({error:"not found"});
    });
  }
  return app;
}

const config=readConfig();
const app=await createBff(config);
await app.listen({host:"0.0.0.0",port:config.PORT});

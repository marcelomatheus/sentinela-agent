import { afterEach, describe, expect, it, vi } from "vitest";
import { createHash, createHmac } from "node:crypto";
import { envSchema } from "../src/config";
import { principalOf, require32Bytes, seal } from "../src/auth";

vi.mock("openid-client", () => ({
  discovery: vi.fn(async () => ({})),
}));

import { createBff } from "../src/index";

const secret = "test-internal-signing-secret-12345678901";
const config = envSchema.parse({
  NODE_ENV:"test", PORT:3005,
  OIDC_ISSUER:"https://identity.example.test",
  OIDC_CLIENT_ID:"sentinela-test",
  BFF_PUBLIC_URL:"https://web.example.test",
  BFF_SESSION_KEY:Buffer.alloc(32,9).toString("base64url"),
  WEB_INTERNAL_KEY:secret,
  SENTINELA_INTERNAL_URL:"http://127.0.0.1:8080",
});
const key=require32Bytes(config.BFF_SESSION_KEY);

async function cookie() {
  const csrf="f".repeat(48);
  const principal=principalOf("https://identity.example.test","test-user");
  const encrypted=await seal({kind:"session",principal,name:"Pessoa",csrf},key,600);
  return {cookie:"sentinela_session="+encrypted,csrf,principal};
}

afterEach(()=>{vi.unstubAllGlobals();});

describe("BFF HTTP integration",()=>{
  it("returns 404 instead of serving frontend or assets",async()=>{
    const app=await createBff(config);
    try{
      for (const path of ["/","/app","/assets/index.js","/unknown"]) {
        const response=await app.inject({
          method:"GET",url:path,headers:{accept:"text/html"},
        });
        expect(response.statusCode).toBe(404);
        expect(response.headers["content-type"]).not.toContain("text/html");
      }
      expect((await app.inject({method:"GET",url:"/health/live"})).statusCode).toBe(200);
    }finally{await app.close();}
  });

  it("does not expose conversations without an authenticated cookie",async()=>{
    const app=await createBff(config);
    try{
      const r=await app.inject({method:"GET",url:"/api/conversations"});
      expect(r.statusCode).toBe(401);
    }finally{await app.close();}
  });

  it("rejects mutations without a valid CSRF token",async()=>{
    const app=await createBff(config);
    const user=await cookie();
    try{
      const r=await app.inject({
        method:"POST",url:"/api/conversations",
        headers:{cookie:user.cookie,"x-csrf-token":"wrong"},
      });
      expect(r.statusCode).toBe(403);
    }finally{await app.close();}
  });

  it("signs the exact downstream URL and serves validated JSON",async()=>{
    const user=await cookie();
    const downstream=vi.fn(async (url:URL,request:RequestInit)=>{
      expect(url.pathname).toBe("/internal/web/conversations");
      expect(request.method).toBe("GET");
      const headers=request.headers as Record<string,string>;
      expect(headers["x-sentinela-principal"]).toBe(user.principal);
      const digest=createHash("sha256").update("").digest("hex");
      const canonical=[
        user.principal,headers["x-sentinela-timestamp"],
        headers["x-sentinela-nonce"],"GET",url.pathname,digest,
      ].join("\n");
      const hmac=createHmac("sha256",secret).update(canonical).digest("hex");
      expect(headers["x-sentinela-signature"]).toBe(hmac);
      return new Response(JSON.stringify({conversations:[]}),{
        headers:{"content-type":"application/json"},
      });
    });
    vi.stubGlobal("fetch",downstream);
    const app=await createBff(config);
    try{
      const response=await app.inject({
        method:"GET",url:"/api/conversations",headers:{cookie:user.cookie},
      });
      expect(response.statusCode).toBe(200);
      expect(response.json()).toEqual({conversations:[]});
      expect(downstream).toHaveBeenCalledOnce();
    }finally{await app.close();}
  });
});

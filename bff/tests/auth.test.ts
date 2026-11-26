import { describe, expect, it } from "vitest";
import { createHmac } from "node:crypto";
import { Identity, internalHeaders, newCsrf, principalOf, require32Bytes, seal, unseal, validCsrf } from "../src/auth";

describe("BFF identity and signed upstream contract",()=>{
  it("derives stable isolated principals",()=>{
    expect(principalOf("issuer","alice")).toHaveLength(64);
    expect(principalOf("issuer","alice")).not.toBe(principalOf("issuer","bob"));
  });
  it("matches Python service signature",()=>{
    const principal=principalOf("https://idp.example","sub-1");
    const signed=internalHeaders(principal,"shared-secret-long-enough-1234567890",1700000000);
    const expected=createHmac("sha256","shared-secret-long-enough-1234567890")
      .update(principal+"\n1700000000").digest("hex");
    expect(signed["x-sentinela-signature"]).toBe(expected);
  });
  it("issues expiring encrypted cookies and rejects modified values",async()=>{
    const key=require32Bytes(Buffer.alloc(32,1).toString("base64url"));
    const csrf=newCsrf();
    const payload={kind:"session",principal:principalOf("iss","user"),name:"Pessoa",csrf};
    const token=await seal(payload,key,600);
    const parsed=Identity.parse(await unseal(token,key));
    expect(parsed.name).toBe("Pessoa");
    expect(validCsrf(parsed,csrf)).toBe(true);
    expect(validCsrf(parsed,"invalid")).toBe(false);
    await expect(unseal(token.slice(0,-2)+"xx",key)).rejects.toThrow();
    expect(()=>require32Bytes("too-short")).toThrow();
  });
});

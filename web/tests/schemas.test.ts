import { describe,expect,it } from "vitest";
import { mediaSchema,newMessageSchema,messageSchema } from "../src/features/chat/api/schemas";

describe("chat contracts",()=>{
  it("rejects empty text and message without file",()=>{
    const base={clientMessageId:crypto.randomUUID(),kind:"text" as const,text:"  "};
    expect(newMessageSchema.safeParse(base).success).toBe(false);
    expect(newMessageSchema.safeParse({...base,kind:"image"}).success).toBe(false);
  });
  it("validates a safe text payload",()=>{
    const message={clientMessageId:crypto.randomUUID(),kind:"text",text:"Recebi uma mensagem suspeita"};
    expect(newMessageSchema.parse(message).kind).toBe("text");
  });
  it("requires consistent response shape",()=>{
    expect(messageSchema.safeParse({status:"completed",risk:"ALTO"}).success).toBe(false);
  });
  it("accepts images but rejects unsupported files",()=>{
    const image=new File([new Uint8Array([0x89,0x50])],"imagem.png",{type:"image/png"});
    const code=new File(["x"],"code.html",{type:"text/html"});
    expect(mediaSchema.safeParse(image).success).toBe(true);
    expect(mediaSchema.safeParse(code).success).toBe(false);
  });
});

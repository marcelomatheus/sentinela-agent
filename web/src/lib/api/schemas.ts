import { z } from "zod";

export const sessionSchema=z.discriminatedUnion("authenticated",[
  z.object({authenticated:z.literal(false)}),
  z.object({
    authenticated:z.literal(true),
    name:z.string(),
    csrf:z.string().length(48),
  }),
]);

export const conversationSchema=z.object({
  id:z.uuid(),title:z.string(),updatedAt:z.string().optional(),
  createdAt:z.string().optional(),
});

export const messageSchema=z.object({
  id:z.uuid(),
  conversationId:z.uuid(),
  role:z.enum(["user","assistant"]),
  kind:z.enum(["text","image","audio"]),
  text:z.string(),
  attachmentId:z.uuid().nullable(),
  status:z.enum(["queued","processing","completed","failed","canceled"]),
  risk:z.enum(["ALTO","MODERADO","INCONCLUSIVO"]).nullable(),
  createdAt:z.string(),
});

export const newMessageSchema=z.object({
  clientMessageId:z.uuid(),
  kind:z.enum(["text","image","audio"]),
  text:z.string().max(4000),
  attachmentId:z.uuid().nullable().optional(),
}).superRefine((data,ctx)=>{
  if(data.kind==="text" && (!data.text.trim() || data.attachmentId)){
    ctx.addIssue({code:"custom",message:"Escreva uma mensagem",path:["text"]});
  }
  if(data.kind!=="text" && !data.attachmentId){
    ctx.addIssue({code:"custom",message:"Selecione um arquivo",path:["attachmentId"]});
  }
});

export const mediaSchema=z.file().max(8000000).mime([
  "image/jpeg","image/png","image/webp","audio/ogg","audio/webm",
  "audio/mpeg","audio/wav",
]);

export type Session=z.infer<typeof sessionSchema>;
export type Conversation=z.infer<typeof conversationSchema>;
export type Message=z.infer<typeof messageSchema>;
export type SendMessage=z.infer<typeof newMessageSchema>;

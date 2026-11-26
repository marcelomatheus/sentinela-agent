import { z } from "zod";
import {
  conversationSchema,messageSchema,mediaSchema,newMessageSchema,sessionSchema,
  type SendMessage,
} from "./schemas";

export class ApiError extends Error {
  constructor(public readonly status:number,message:string){super(message);}
}

export async function apiFetch<T>(
  path:string, schema:z.ZodType<T>,
  opts:{method?:string;csrf?:string;body?:BodyInit;headers?:Record<string,string>}={},
):Promise<T> {
  const response=await fetch("/api"+path,{
    method:opts.method??"GET",body:opts.body,
    headers:{
      ...opts.headers,...(opts.csrf?{"x-csrf-token":opts.csrf}:{})
    },
    credentials:"same-origin",cache:"no-store",
  });
  if(!response.ok){
    const error=await response.json().catch(()=>({error:"Não foi possível concluir a operação."})) as {error?:string};
    throw new ApiError(response.status,error.error??"Erro inesperado");
  }
  if(response.status===204) return schema.parse(undefined);
  return schema.parse(await response.json());
}

const conversations=z.object({conversations:z.array(conversationSchema)});
const messages=z.object({messages:z.array(messageSchema)});
const sent=z.object({message:messageSchema,duplicate:z.boolean()});
const attachment=z.object({id:z.uuid(),mime:z.string(),size:z.number()});

export const client={
  session:()=>apiFetch("/session",sessionSchema),
  conversations:()=>apiFetch("/conversations",conversations),
  newConversation:(csrf:string)=>apiFetch("/conversations",conversationSchema,{method:"POST",csrf}),
  messages:(id:string,before?:string)=>apiFetch(
    `/conversations/${id}/messages${before?"?before="+encodeURIComponent(before):""}`,messages,
  ),
  send:(id:string,payload:SendMessage,csrf:string)=>apiFetch(
    `/conversations/${id}/messages`,sent,{
      method:"POST",csrf,body:JSON.stringify(newMessageSchema.parse(payload)),
      headers:{"content-type":"application/json"},
    },
  ),
  upload:async(id:string,file:File,csrf:string)=>{
    mediaSchema.parse(file);
    if(file.type.startsWith("audio/") && file.size>1000000){
      throw new Error("Áudio deve ter até 1 MB.");
    }
    const form=new FormData();
    form.append("file",file,file.name);
    return apiFetch(`/conversations/${id}/attachments`,attachment,{
      method:"POST",csrf,body:form,
    });
  },
  reset:async(id:string,csrf:string)=>{
    const response=await fetch(`/api/conversations/${id}/reset`,{
      method:"POST",headers:{"x-csrf-token":csrf},
      credentials:"same-origin",
    });
    if(!response.ok) throw new ApiError(response.status,"Não foi possível reiniciar o caso");
  },
  delete:async(id:string,csrf:string)=>{
    const response=await fetch(`/api/conversations/${id}`,{
      method:"DELETE",headers:{"x-csrf-token":csrf},
      credentials:"same-origin",
    });
    if(!response.ok) throw new ApiError(response.status,"Não foi possível excluir a conversa");
  },
  logout:async(csrf:string)=>{
    const response=await fetch("/auth/logout",{
      method:"POST",headers:{"x-csrf-token":csrf},
      credentials:"same-origin",
    });
    if(!response.ok) throw new ApiError(response.status,"Falha ao sair");
  },
};

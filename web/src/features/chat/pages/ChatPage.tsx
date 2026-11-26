import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import {
  ArrowRight, CircleHelp, History, Menu, MessageCircle,
  Plus, ShieldCheck, Sparkles,
} from "lucide-react";
import type { Session, Message } from "../api/schemas";
import { client } from "../../../lib/api/client";
import Composer from "../components/Composer";
import MessageFeed from "../components/MessageFeed";
import HistorySidebar from "../../conversations";

type ActiveSession=Extract<Session,{authenticated:true}>;

const suggestions=[
  {label:"Mensagem bancária",prompt:"Recebi uma mensagem que parece ser de um banco e estou desconfiando."},
  {label:"Link suspeito",prompt:"Recebi um link inesperado e quero entender se pode ser perigoso."},
  {label:"Pedido de PIX",prompt:"Uma pessoa pediu um PIX urgente. Como posso conferir se é golpe?"},
];

export default function ChatPage({session}:{session:ActiveSession}){
  const {conversationId}=useParams<{conversationId:string}>();
  const navigate=useNavigate();
  const cache=useQueryClient();
  const [drawer,setDrawer]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState<string|null>(null);
  const [older,setOlder]=useState<Message[]>([]);
  const [hasMore,setHasMore]=useState(true);
  const [connected,setConnected]=useState(false);
  const latest=useQuery({
    queryKey:["messages",conversationId],
    queryFn:()=>client.messages(conversationId!),
    enabled:!!conversationId,
  });
  useEffect(()=>{setOlder([]);setHasMore(true);},[conversationId]);

  useEffect(()=>{
    if(!conversationId)return;
    const source=new EventSource(`/api/conversations/${conversationId}/events`,{withCredentials:true});
    source.onopen=()=>setConnected(true);
    source.onerror=()=>setConnected(false);
    const update=()=>{void cache.invalidateQueries({queryKey:["messages",conversationId]});};
    source.addEventListener("message",update);
    source.addEventListener("processing",update);
    source.addEventListener("failed",update);
    source.addEventListener("reset",update);
    return ()=>{source.close();setConnected(false);};
  },[conversationId,cache]);

  const entries=useMemo(()=>{
    const set=new Map<string,Message>();
    [...older,...(latest.data?.messages??[])].forEach(value=>set.set(value.id,value));
    return [...set.values()].sort((a,b)=>
      a.createdAt.localeCompare(b.createdAt)||a.id.localeCompare(b.id)
    );
  },[older,latest.data?.messages]);

  const reset=useMutation({
    mutationFn:async()=>client.reset(conversationId!,session.csrf),
    onSuccess:()=>{void cache.invalidateQueries({queryKey:["messages",conversationId]});},
  });

  async function submit(text:string,file:File|null){
    setBusy(true);setError(null);
    try{
      let id=conversationId;
      if(!id){
        const created=await client.newConversation(session.csrf);
        id=created.id;
        void cache.invalidateQueries({queryKey:["conversations"]});
        navigate(`/app/chat/${id}`,{replace:true});
      }
      let attachmentId:string|undefined;
      if(file){
        const attachment=await client.upload(id,file,session.csrf);
        attachmentId=attachment.id;
      }
      await client.send(id,{
        clientMessageId:crypto.randomUUID(),
        kind:file?(file.type.startsWith("audio/")?"audio":"image"):"text",
        text,attachmentId,
      },session.csrf);
      void cache.invalidateQueries({queryKey:["messages",id]});
      void cache.invalidateQueries({queryKey:["conversations"]});
    }catch(cause){
      const reason=cause instanceof Error?cause.message:"Não foi possível enviar a mensagem";
      setError(reason);
      throw cause;
    }finally{setBusy(false);}
  }

  async function loadEarlier(){
    if(!conversationId||!entries.length)return;
    const page=await client.messages(conversationId,entries[0]!.createdAt);
    setOlder(current=>[...page.messages,...current]);
    if(page.messages.length<50)setHasMore(false);
  }

  const isEmpty=(!conversationId||(!latest.isPending&&entries.length===0));
  const analyzing=entries.some(m=>m.role==="user"&&(m.status==="queued"||m.status==="processing"));
  return <div className="chat-shell">
    <aside className="icon-rail" aria-label="Ações principais">
      <a href="/" className="rail-logo" aria-label="Ir para home"><ShieldCheck size={24}/></a>
      <div className="rail-actions">
        <button title="Histórico" aria-label="Abrir histórico" type="button" className="rail-active"
          onClick={()=>setDrawer(true)}><History size={20}/></button>
        <button title="Nova análise" aria-label="Nova análise" type="button"
          onClick={()=>navigate("/app")}><Plus size={21}/></button>
      </div>
      <button title="Sobre o Sentinela" type="button" className="rail-bottom"
        aria-label="Sobre o Sentinela" onClick={()=>window.open("/#seguranca","_blank","noopener,noreferrer")}>
        <CircleHelp size={20}/>
      </button>
    </aside>
    <HistorySidebar activeId={conversationId} csrf={session.csrf} name={session.name}
      visible={drawer} onClose={()=>setDrawer(false)}/>
    <main className="chat-main">
      <div className="chat-header">
        <div className="chat-header-left">
          <button type="button" aria-label="Abrir histórico" className="header-menu" onClick={()=>setDrawer(true)}><Menu size={21}/></button>
          <div className="chat-product">
            <div className="chat-product-icon"><ShieldCheck size={19}/></div>
            <div><strong>Sentinela</strong><small>Assistente de segurança digital</small></div>
          </div>
        </div>
        <div className="chat-header-right">
          <span className={connected?"chat-live connected":"chat-live"}>
            <span/>{conversationId?(connected?"Conectado":"Reconectando"):"Pronto para conversar"}
          </span>
          <button className="header-new" type="button" onClick={()=>navigate("/app")}>
            <Plus size={17}/> Nova conversa
          </button>
        </div>
      </div>
      {isEmpty?<div className="chat-welcome">
        <div className="welcome-halo" aria-hidden="true"/>
        <div className="welcome-content">
          <div className="welcome-symbol"><ShieldCheck size={28}/></div>
          <p className="welcome-kicker">SENTINELA · CONVERSA SEGURA</p>
          <h1>O que você <span>recebeu?</span></h1>
          <p className="welcome-subtitle">Pode me contar o que aconteceu, colar uma mensagem ou enviar uma imagem ou áudio suspeito.</p>
        </div>
        <div className="welcome-input">
          <Composer onSend={submit} busy={busy}/>
          <div className="suggestion-row">
            {suggestions.map(item=><button key={item.label} type="button" onClick={()=>void submit(item.prompt,null)}
              disabled={busy}><Sparkles size={14}/>{item.label}<ArrowRight size={14}/></button>)}
          </div>
        </div>
      </div>:<div className="conversation-view">
        <MessageFeed messages={entries} isLoading={latest.isPending} busy={analyzing}
          hasMore={hasMore&&entries.length>=50} onLoadEarlier={()=>void loadEarlier()}/>
        <div className="chat-bottom">
          {error&&<p className="chat-error" role="alert">{error}</p>}
          <Composer onSend={submit} busy={busy}/>
          <div className="composer-disclaimer">
            <MessageCircle size={12}/> O Sentinela indica sinais de alerta, mas não garante que algo seja seguro.
            {conversationId&&<button type="button" onClick={()=>{if(window.confirm("Começar outro caso nesta conversa?"))reset.mutate();}}>Reiniciar caso</button>}
          </div>
        </div>
      </div>}
      <div className="chat-corner-orb" aria-hidden="true"/>
    </main>
  </div>;
}

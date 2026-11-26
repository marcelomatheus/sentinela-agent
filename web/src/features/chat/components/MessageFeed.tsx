import { useEffect, useRef } from "react";
import { AlertTriangle, CheckCircle2, CircleHelp, Copy, LoaderCircle, ShieldCheck } from "lucide-react";
import type { Message } from "../api/schemas";

function RiskTag({risk}:{risk:Message["risk"]}){
  if(!risk)return null;
  const Icon=risk==="ALTO"?AlertTriangle:risk==="MODERADO"?CircleHelp:CheckCircle2;
  return <span className={`risk-tag risk-${risk.toLowerCase()}`}>
    <Icon size={13}/>{risk==="ALTO"?"Possível golpe":risk==="MODERADO"?"Atenção":"Inconclusivo"}
  </span>;
}

export default function MessageFeed({
  messages,isLoading,onLoadEarlier,busy,hasMore,
}:{
  messages:Message[];isLoading:boolean;
  onLoadEarlier?:()=>void;busy?:boolean;hasMore?:boolean;
}){
  const bottom=useRef<HTMLDivElement>(null);
  useEffect(()=>{bottom.current?.scrollIntoView({behavior:"smooth",block:"end"});},[messages.length]);
  return <div className="message-feed" role="log" aria-label="Mensagens da conversa" aria-live="polite">
    <div className="message-list">
      {hasMore&&<button type="button" className="load-earlier" onClick={onLoadEarlier}>Carregar mensagens anteriores</button>}
      {isLoading&&<div className="feed-loading"><LoaderCircle className="spin"/> Carregando conversa...</div>}
      {messages.map(message=><div key={message.id} className={`message-row ${message.role==="user"?"user":"assistant"}`}>
        {message.role==="assistant"&&<div className="assistant-avatar"><ShieldCheck size={18}/></div>}
        <div className="message-content">
          <div className="message-meta">{message.role==="assistant"?"Sentinela":"Você"}</div>
          <div className="message-bubble">
            {message.role==="assistant"&&<RiskTag risk={message.risk}/>}
            {message.kind==="image"&&<span className="attachment-kind">Imagem anexada</span>}
            {message.kind==="audio"&&<span className="attachment-kind">Áudio anexado</span>}
            {message.text&&<p>{message.text}</p>}
            {message.status==="queued"&&<small className="message-status">Aguardando análise...</small>}
            {message.status==="processing"&&<small className="message-status">Analisando...</small>}
            {message.status==="failed"&&<small className="message-status error">Falha no processamento</small>}
          </div>
          {message.role==="assistant"&&<button type="button" className="copy-message"
            title="Copiar resposta" aria-label="Copiar resposta"
            onClick={()=>void navigator.clipboard.writeText(message.text)}><Copy size={13}/> Copiar</button>}
        </div>
      </div>)}
      {busy&&<div className="typing-indicator"><span/><span/><span/> Sentinela analisando</div>}
      <div ref={bottom}/>
    </div>
  </div>;
}

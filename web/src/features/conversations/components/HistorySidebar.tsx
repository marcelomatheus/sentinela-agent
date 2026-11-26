import { LogOut, MessageSquarePlus, ShieldCheck, Trash2, X } from "lucide-react";
import { NavLink, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { client } from "../../../lib/api/client";

export default function HistorySidebar({
  activeId,csrf,name,visible,onClose,
}:{
  activeId?:string;csrf:string;name:string;visible:boolean;onClose:()=>void;
}){
  const navigate=useNavigate();
  const cache=useQueryClient();
  const list=useQuery({queryKey:["conversations"],queryFn:client.conversations});
  const remove=useMutation({
    mutationFn:(id:string)=>client.delete(id,csrf),
    onSuccess:(_result,id)=>{
      void cache.invalidateQueries({queryKey:["conversations"]});
      if(activeId===id)navigate("/app");
    },
  });
  const logout=useMutation({mutationFn:()=>client.logout(csrf),onSuccess:()=>{window.location.href="/";}});
  return <>
    {visible&&<button type="button" className="drawer-backdrop" aria-label="Fechar histórico" onClick={onClose}/>}
    <aside className={visible?"chat-sidebar open":"chat-sidebar"} aria-label="Histórico de conversas">
      <div className="sidebar-top">
        <NavLink className="sidebar-logo" to="/" title="Sentinela"><ShieldCheck/><span>SENTINELA</span></NavLink>
        <button type="button" className="icon-button sidebar-close" aria-label="Fechar" onClick={onClose}><X size={19}/></button>
      </div>
      <button type="button" className="new-conversation" onClick={()=>{navigate("/app");onClose();}}>
        <MessageSquarePlus size={17}/> Nova análise
      </button>
      <div className="history-heading">SUAS CONVERSAS</div>
      <div className="history-items">
        {list.isLoading&&<p className="sidebar-hint">Carregando conversas...</p>}
        {list.data?.conversations.length===0&&<p className="sidebar-hint">Suas análises aparecerão aqui.</p>}
        {list.data?.conversations.map(item=><div className={item.id===activeId?"history-item active":"history-item"} key={item.id}>
          <NavLink to={`/app/chat/${item.id}`} onClick={onClose} title={item.title}>
            <span className="history-dot"/><span className="history-title">{item.title}</span>
          </NavLink>
          <button className="history-delete" type="button"
            disabled={remove.isPending} title="Excluir conversa"
            aria-label={`Excluir ${item.title}`}
            onClick={()=>{
              if(window.confirm("Excluir esta conversa e seu histórico?"))remove.mutate(item.id);
            }}><Trash2 size={15}/></button>
        </div>)}
      </div>
      <div className="sidebar-user">
        <div className="user-avatar">{name.slice(0,1).toUpperCase()}</div>
        <div className="user-info"><strong>{name}</strong><small>Conta conectada</small></div>
        <button type="button" className="icon-button" title="Sair" aria-label="Sair"
          disabled={logout.isPending} onClick={()=>logout.mutate()}><LogOut size={17}/></button>
      </div>
    </aside>
  </>;
}

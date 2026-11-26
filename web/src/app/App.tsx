import { Navigate, Route, Routes } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { client } from "../lib/api/client";
import HomePage from "../features/home/pages/HomePage";
import ChatPage from "../features/chat/pages/ChatPage";

export default function App(){
  const session=useQuery({queryKey:["session"],queryFn:client.session,retry:0});
  return <Routes>
    <Route path="/" element={<HomePage authenticated={session.data?.authenticated===true}/>}/>
    <Route path="/app" element={
      session.isPending?<div className="screen-loading"><ShieldCheck/> Conectando ao Sentinela...</div>:
      session.data?.authenticated?<ChatPage session={session.data}/>:<Navigate to="/?login=1" replace/>
    }/>
    <Route path="/app/chat/:conversationId" element={
      session.isPending?<div className="screen-loading"><ShieldCheck/> Conectando...</div>:
      session.data?.authenticated?<ChatPage session={session.data}/>:<Navigate to="/?login=1" replace/>
    }/>
    <Route path="*" element={<Navigate to="/" replace/>}/>
  </Routes>;
}

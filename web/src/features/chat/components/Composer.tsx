import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { ArrowUp, AudioLines, FileImage, LoaderCircle, Mic, Paperclip, Square, X } from "lucide-react";
import { mediaSchema } from "../api/schemas";

export default function Composer({
  onSend,busy=false,
}:{
  onSend:(text:string,file:File|null)=>Promise<void>;
  busy?:boolean;
}){
  const [text,setText]=useState("");
  const [file,setFile]=useState<File|null>(null);
  const [error,setError]=useState<string|null>(null);
  const [recording,setRecording]=useState(false);
  const fileInput=useRef<HTMLInputElement>(null);
  const recorder=useRef<MediaRecorder|null>(null);
  const mediaStream=useRef<MediaStream|null>(null);
  const textarea=useRef<HTMLTextAreaElement>(null);

  useEffect(()=>()=>{recorder.current?.stop();mediaStream.current?.getTracks().forEach(t=>t.stop());},[]);

  function choose(chosen:File|undefined){
    if(!chosen)return;
    const result=mediaSchema.safeParse(chosen);
    if(!result.success){setError("Formato inválido ou arquivo maior que 8 MB.");return;}
    if(chosen.type.startsWith("audio/")&&chosen.size>1000000){
      setError("Áudios podem ter até 1 MB.");return;
    }
    setError(null);setFile(chosen);
  }
  async function send(event?:FormEvent){
    event?.preventDefault();
    if(busy||(!text.trim()&&!file))return;
    setError(null);
    try{
      await onSend(text.trim(),file);
      setText("");setFile(null);
      if(fileInput.current)fileInput.current.value="";
      textarea.current?.focus();
    }catch(cause){setError(cause instanceof Error?cause.message:"Não foi possível enviar.");}
  }
  function onKey(event:KeyboardEvent<HTMLTextAreaElement>){
    if(event.key==="Enter"&&!event.shiftKey&&!event.nativeEvent.isComposing){
      event.preventDefault();void send();
    }
  }
  async function startRecording(){
    try{
      if(!navigator.mediaDevices?.getUserMedia||!window.MediaRecorder||
        !MediaRecorder.isTypeSupported("audio/webm")){
        setError("A gravação de áudio não é compatível com este navegador.");return;
      }
      const stream=await navigator.mediaDevices.getUserMedia({audio:true});
      mediaStream.current=stream;
      const chunks:Blob[]=[];
      const instance=new MediaRecorder(stream,{mimeType:"audio/webm"});
      recorder.current=instance;
      instance.ondataavailable=e=>{if(e.data.size)chunks.push(e.data);};
      instance.onstop=()=>{
        stream.getTracks().forEach(track=>track.stop());
        setRecording(false);
        const blob=new Blob(chunks,{type:"audio/webm"});
        choose(new File([blob],"audio-suspeito.webm",{type:"audio/webm"}));
      };
      instance.start();setRecording(true);setError(null);
    }catch{setError("Não foi possível acessar o microfone.");}
  }
  function stopRecording(){if(recorder.current?.state==="recording")recorder.current.stop();}
  return <form className="composer" onSubmit={e=>void send(e)}
    onDragOver={e=>e.preventDefault()}
    onDrop={e=>{e.preventDefault();choose(e.dataTransfer.files[0]);}}
  >
    <div className="composer-glow" aria-hidden="true"/>
    <div className="composer-inner">
      <textarea ref={textarea} id="chat-composer" aria-label="Mensagem para o Sentinela"
        rows={2} maxLength={4000} placeholder="Conte o que aconteceu ou cole uma mensagem suspeita..."
        value={text} onChange={e=>setText(e.target.value)} onKeyDown={onKey}
        disabled={busy} />
      {file&&<div className="file-preview">
        {file.type.startsWith("audio/")?<AudioLines size={16}/>:<FileImage size={16}/>}
        <span>{file.name}</span><small>{Math.ceil(file.size/1024)} KB</small>
        <button type="button" aria-label="Remover arquivo" onClick={()=>setFile(null)}><X size={15}/></button>
      </div>}
      {error&&<p role="alert" className="composer-error">{error}</p>}
      <div className="composer-actions">
        <div className="composer-tools">
          <input ref={fileInput} type="file" hidden
            accept="image/png,image/jpeg,image/webp,audio/ogg,audio/webm,audio/mpeg,audio/wav"
            onChange={e=>choose(e.target.files?.[0])}/>
          <button type="button" title="Anexar imagem ou áudio" aria-label="Anexar arquivo"
            onClick={()=>fileInput.current?.click()} disabled={busy}><Paperclip size={18}/><span>Anexar</span></button>
          <button type="button" className={recording?"recording":""}
            title={recording?"Parar gravação":"Gravar áudio"}
            onClick={()=>recording?stopRecording():void startRecording()} disabled={busy}>
            {recording?<Square size={17}/>:<Mic size={18}/>}
            <span>{recording?"Parar":"Áudio"}</span>
          </button>
        </div>
        <button type="submit" className="send-button" aria-label="Enviar mensagem"
          disabled={busy||recording||(!text.trim()&&!file)}>
          {busy?<LoaderCircle className="spin" size={18}/>:<ArrowUp size={19}/>}
        </button>
      </div>
    </div>
  </form>;
}

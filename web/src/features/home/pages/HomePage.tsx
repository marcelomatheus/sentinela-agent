import { ArrowRight, CheckCheck, Fingerprint, Shield, ShieldCheck, Sparkles, Zap } from "lucide-react";
import { Link } from "react-router-dom";

export default function HomePage({authenticated}:{authenticated:boolean}){
  return <main className="landing">
    <header className="landing-nav">
      <Link to="/" className="brand"><span className="brand-mark"><ShieldCheck size={23}/></span><span>SENTINELA</span></Link>
      <nav aria-label="Navegação principal">
        <a href="#como-funciona">Como funciona</a>
        <a href="#seguranca">Segurança</a>
      </nav>
      <a className="nav-cta" href={authenticated?"/app":"/auth/login"}>
        {authenticated?"Abrir chat":"Entrar"} <ArrowRight size={15}/>
      </a>
    </header>
    <section className="landing-hero">
      <div className="landing-copy">
        <p className="eyebrow"><span className="eyebrow-dot"/> INTELIGÊNCIA A SERVIÇO DA SUA SEGURANÇA</p>
        <h1>Antes de<br/><span>confiar,</span><br/>converse.</h1>
        <p className="hero-subtitle">
          Um olhar atento para mensagens, links e pedidos suspeitos.
          Envie sua dúvida e receba uma orientação clara, sem julgamentos.
        </p>
        <div className="hero-actions">
          <a className="button-primary" href={authenticated?"/app":"/auth/login"}>
            Analisar mensagem <ArrowRight size={18}/>
          </a>
          <a className="button-outline" href="#como-funciona">Conhecer o Sentinela</a>
        </div>
        <div className="hero-trust">
          <span><CheckCheck size={16}/> Texto, imagem e áudio</span>
          <span><ShieldCheck size={16}/> Orientação responsável</span>
        </div>
      </div>
      <div className="hero-art" aria-hidden="true">
        <div className="hero-halo"/>
        <div className="orb-back"/>
        <div className="hero-orb"><div className="hero-orb-shine"/></div>
        <div className="orbit orbit-a"/><div className="orbit orbit-b"/>
        <div className="floating-insight insight-top"><Fingerprint size={22}/><span>Uma análise mais atenta</span></div>
        <div className="floating-insight insight-bottom"><Shield size={22}/><span>Mais confiança para decidir</span></div>
      </div>
      <div className="vertical-label" aria-hidden="true">ENTENDA OS SINAIS · EVITE O GOLPE</div>
    </section>
    <section id="como-funciona" className="landing-process">
      <div className="section-label">SIMPLES DO COMEÇO AO FIM</div>
      <div className="process-heading"><h2>Seu próximo passo,<br/>com mais clareza.</h2><p>Você não precisa entender de segurança digital para fazer uma pergunta.</p></div>
      <div className="process-grid">
        <article><span className="step-number">01</span><div className="step-icon"><Sparkles/></div><h3>Compartilhe a situação</h3><p>Cole a mensagem ou envie uma imagem ou áudio suspeito.</p></article>
        <article><span className="step-number">02</span><div className="step-icon"><Zap/></div><h3>Entenda os indícios</h3><p>O Sentinela interpreta os fatos e verifica sinais comuns de fraude.</p></article>
        <article><span className="step-number">03</span><div className="step-icon"><ShieldCheck/></div><h3>Saiba como agir</h3><p>Receba orientação objetiva para verificar a situação com segurança.</p></article>
      </div>
    </section>
    <section id="seguranca" className="landing-ethics">
      <div className="ethics-icon"><ShieldCheck size={40}/></div>
      <div><p className="section-label">SEGURANÇA EM PRIMEIRO LUGAR</p><h2>Nem todo alerta é um golpe.<br/>Nem toda mensagem é segura.</h2><p>O Sentinela identifica indícios e explica cuidados. Não substitui canais oficiais ou garante que uma mensagem seja legítima.</p></div>
      <a href={authenticated?"/app":"/auth/login"} className="button-primary">Começar análise <ArrowRight size={18}/></a>
    </section>
    <footer className="landing-footer"><span>SENTINELA © 2026</span><span>Desenvolvido com responsabilidade.</span></footer>
  </main>;
}

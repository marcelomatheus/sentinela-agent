# Sentinela multicanal — implementação Web + BFF

## Arquitetura em produção

**WhatsApp** → Evolution webhook → fila `app.inbox` → worker WhatsApp → `AnalyzeMessage`.
**React** → BFF Fastify (OIDC/PKCE) → endpoints internos FastAPI autenticados → `app.web_jobs` → N workers web → **mesmo `AnalyzeMessage`** → `app.web_messages` e `app.web_events` → SSE.

O BFF **não** executa Agno, OpenAI nem regras: atua como sessão web, autorização, proteção CSRF, validação Zod e tradução do contrato. O motor Python mantém as 12 regras, guardrails, política de risco e saída textual idênticos entre canais. As sessões e fatos são separados por canal e por conversa; `session_id` nunca é compartilhado.

## Desenvolvimento e versões

- React 19.3.1, Vite 8.4.0, TypeScript 7.0.2 e Zod 4.6.7.
- Monorepo npm workspaces (`web/`, `bff/`). Instalação reproduzível via `npm ci` e `package-lock.json`.
- `npm run dev:web` porta 5173 (Vite proxy /api e /auth para BFF 3005).
- `npm run dev:bff` porta 3005. Exige issuer OIDC e segredos mesmo em dev.
- `npm run typecheck && npm run test && npm run build`.

O backend segue em Python 3.15.2 e Poetry 2.2.1, usando o `poetry.lock` existente.

## Configuração para VPS

1. Gere 32 bytes aleatórios em base64url para `BFF_SESSION_KEY`, por exemplo:
   `python -c "import base64,secrets;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip('='))"`
2. Gere `WEB_INTERNAL_KEY` com pelo menos 32 caracteres aleatórios; use **o mesmo valor** em FastAPI e BFF, somente na rede Docker privada.
3. Registre um cliente OIDC de aplicação web com callback `https://SEU_DOMINIO/auth/callback`. Configure `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` (se cliente confidencial) e `BFF_PUBLIC_URL`.
4. Mantenha `BFF_ALLOW_HTTP=false` em produção. Configure HTTPS no reverse proxy que encaminha ao host loopback `127.0.0.1:${BFF_PORT:-3005}`. **Nunca publique a porta FastAPI nem o PostgreSQL diretamente.**
5. `docker compose --profile web up -d --build`. O processo FastAPI aplica a migração idempotente `db/002_web.sql`, e o worker web também a verifica ao subir.
6. Acesse o domínio; login OIDC → home → chat. O BFF serve o SPA compilado, protege o cookie HttpOnly e assina identidade para a API Python.

## Garantias e limitações

### Sessões e segurança
- BFF tem cookie JWE AES-256-GCM, `HttpOnly`, `SameSite=Lax`, `Secure` em produção, duração de 8 h; transação OIDC usa state, nonce e PKCE.
- Mutação de dados exige `X-CSRF-Token`, obtido de `GET /api/session` pelo próprio SPA.
- Identidade interna é SHA-256 de `issuer + subject`; a API valida assinatura HMAC-SHA256 com timestamp de até ±60 segundos. Todas as consultas aplicam `owner_id`.
- O WhatsApp segue na própria `app.inbox/app.sessions` e não adota identidade web automaticamente.
- Evidências anexadas são privadas em `web_media` (volume com permissão restrita), verificadas por assinatura de arquivo, MIME, tamanho e checksum. Áudio até 1 MB, imagens até 8 MB. Em produção multi-host, substitua volume local por armazenamento privado S3 compatível, sem alterar o núcleo.
- Conteúdo de mensagem é exibido apenas como texto React, sem HTML arbitrário ou Markdown não confiável.
- Retenção: eventos web acima de 14 dias e uploads não utilizados acima de 1 dia são descartados pelo worker. A exclusão da conversa remove dados e anexos conhecidos.

### Concorrência e recuperação
- Worker WhatsApp mantém seu lock global legado. Web executa workers concorrentes sem esse lock: `FOR UPDATE SKIP LOCKED` e ordem por conversa.
- Cada job tem lease de 120 s com renovação a cada 20 s; após falha, leases expirados retornam para `pending`. A conclusão exige `lease_token` idêntico, impedindo escrita de processos obsoletos.
- Reiniciar uma conversa incrementa `generation`, cancela jobs pendentes e impede que um worker antigo grave sua resposta numa sessão nova.
- A criação de mensagem usa `clientMessageId` UUID e constraint única para tolerar retransmissões; resposta e evento SSE são gravados numa transação.
- Pool PostgreSQL web de no máximo seis conexões por processo; o limite total deve considerar as instâncias de API e os workers da VPS.
- A fila e SSE operam no PostgreSQL. O evento é recuperável por cursor, mas não oferece exatamente uma vez na renderização do browser (a UI deduplica pelo UUID).
- O BFF usa endpoints HTTP internos e não mantém dados de conversa em memória; portanto, pode escalar horizontalmente atrás de um proxy. Os cookies JWE exigem a mesma chave entre réplicas.

### Produção
Ainda é necessária validação real de login OIDC, uploads por navegadores diferentes, concorrência e carga no hardware da VPS. A CI verifica contratos, testes Python e Node, build dos dois contêineres e migração em PostgreSQL descartável. Não declare throughput nem latência sem benchmark.

## Organização Bulletproof React
`web/src/app` contém a aplicação e estilos globais; `features/home`, `features/chat` e `features/conversations` encapsulam UI e estado da feature; `lib/api` é o limite de contrato com o BFF, validado por Zod. Não são importadas regras Python no frontend.

A home usa objeto iridescente CSS e tipografia editorial, baseada em referências visuais, sem imagens pesadas nem WebGL. O chat usa navegação lateral, compositor destacado, suporte a teclado, aria-labels, mídia e estados SSE. `prefers-reduced-motion` desativa animações.

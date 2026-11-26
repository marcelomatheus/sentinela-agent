# Sentinela Web — deploy com Traefik e Cloudflare Tunnel da VPS

Referência: [deploy do PivôNauta](https://github.com/marcelomatheus/pesquisa-operacional/blob/main/docs/DEPLOY_TRAEFIK_MANUAL.md). Reutiliza **Traefik e Cloudflare Tunnel existentes**, sem criar borda, sem publicar portas da aplicação no host, sem tocar em outros projetos e sem enviar imagens ao Docker Hub.

## Arquitetura

```text
Usuário HTTPS
    |
Cloudflare Tunnel (já instalado)
    |  http://traefik:80, mantendo o Host original
Traefik (rede Docker externa celo-network)
    |-- Host(DOMAIN_NAME) + /api/** ou /auth/** -> sentinela-bff:19573
    |-- Host(DOMAIN_NAME) + demais caminhos  -> sentinela-web:18561
                                                  React estático (Nginx)
BFF Fastify :19573 --rede default privada--> FastAPI :8080 -> PostgreSQL
                                                        |          |
                                                  worker web     volume pgdata
API + worker WhatsApp --- whatsapp_internal ---> Evolution existente
```

**Portas não convencionais:** frontend **18561**, BFF **19573**, ambas **somente internas ao Docker**. Não há `ports` para web/BFF e nenhum mapeamento dessas portas no host. Assim, não podem conflitar com bind de outros projetos; o Traefik identifica destinos por labels e rede. A porta legada 8080 da API continua acessível apenas via loopback do host, para não alterar a topologia WhatsApp atual. PostgreSQL não publica portas.

O frontend usa uma imagem Nginx separada da imagem Fastify, cujo servidor ainda contém o SPA como fallback. Entretanto, no domínio de produção o Traefik faz o roteamento separado: o BFF recebe as rotas /api e /auth **diretamente**, incluindo SSE (sem um Nginx adicional que possa fazer buffering), e todas as demais rotas seguem para o React. Os dois serviços usam o mesmo hostname (sem CORS), portanto os cookies seguros HttpOnly e o fluxo OIDC/PKCE funcionam na mesma origem.

## Preparar a VPS

**Importante: este é um overlay do mesmo projeto Compose**, não uma instalação independente. Aplique os dois arquivos **no mesmo diretório da instalação Sentinela existente**, mantendo `.env` e o mesmo nome de projeto Compose. Assim, o PostgreSQL (`pgdata`) e anexos (`web_media`) permanecem nos mesmos volumes. **Não use `compose.production.yaml` sozinho**, não mude `COMPOSE_PROJECT_NAME` e não execute `down -v`. Faça backup do banco antes da primeira atualização.

Requer Docker Compose com suporte ao operador YAML `!reset` (v2.24 ou posterior), usado para remover a porta local 3005 do BFF herdada do compose de desenvolvimento.

1. Confirme que Traefik e Cloudflare Tunnel já estão ativos. `docker network inspect celo-network` deve funcionar, assim como `docker network inspect whatsapp_internal`. A rede real do Traefik pode ser configurada em `PROXY_NETWORK`. Não recrie redes já existentes.
2. Em `.env`, mantenha **todas as configurações já existentes** do Sentinela e acrescente:

```dotenv
DOMAIN_NAME=sentinela.seu-dominio.com
PROXY_NETWORK=celo-network
TRAEFIK_ENTRYPOINT=web
BFF_PUBLIC_URL=https://sentinela.seu-dominio.com
BFF_ALLOW_HTTP=false
# Necessarios tambem OIDC_ISSUER, OIDC_CLIENT_ID,
# BFF_SESSION_KEY, WEB_INTERNAL_KEY e chaves anteriores.
```

`DOMAIN_NAME` deve conter somente o hostname (sem esquema, porta ou caminho) e coincidir com o valor de `BFF_PUBLIC_URL`. O Compose de produção substitui `BFF_PUBLIC_URL` com `https://DOMAIN_NAME`, tornando-o a origem canônica da sessão. Gere uma chave BFF de **32 bytes em base64url** com o comando do guia `docs/web-multicanal.md`, e um segredo HMAC independente de pelo menos 32 caracteres. Proteja `.env` com `chmod 600 .env`. O BFF faz descoberta OIDC ao iniciar e exige o issuer acessível pela VPS.

3. No provedor OIDC, cadastre **exatamente** o redirect URI `https://sentinela.seu-dominio.com/auth/callback`. O cookie OAuth é `SameSite=Lax`, `Secure` e `HttpOnly`.

4. No painel do **Cloudflare Tunnel existente**, adicione um novo Public Hostname apontando ao origin **`http://traefik:80`** (ou o endpoint interno efetivo do stack da VPS). Preserve o cabeçalho HTTP **Host** original para que os routers `Host(DOMAIN_NAME)` do Traefik funcionem. O TLS público termina no Cloudflare; no padrão do PivôNauta, o entrypoint `web` do Traefik recebe HTTP interno. Não altere ou reinicie o Tunnel/Traefik nem a configuração dos outros domínios.

## Subir sem recriar volumes

```bash
cd /opt/sentinela  # ajuste para o diretório atual
git pull --ff-only  # após revisar e mesclar a PR
chmod 600 .env
bash scripts/deploy_traefik.sh
```

O script confere a topologia renderizada e verifica a existência das duas redes compartilhadas **antes** do `up`. Depois usa:

```bash
docker compose -f compose.yaml -f compose.production.yaml --profile web up -d --build --wait
```

Atenção: `up --build` pode recriar containers do próprio Sentinela, inclusive WhatsApp, durante a transição, causando breve interrupção. Ele não altera o stack externo do Traefik, Cloudflare ou Evolution. Para atualizações seletivas futuras, use `up -d --no-deps --build web bff` se as respectivas dependências estiverem saudáveis. Faça backup e confirme disponibilidade da API antes de atualizar.

## Verificar

```bash
docker compose -f compose.yaml -f compose.production.yaml --profile web ps
docker compose -f compose.yaml -f compose.production.yaml --profile web config --format json > /tmp/sentinela-compose.json
python3 scripts/check_production_compose.py /tmp/sentinela-compose.json
docker compose -f compose.yaml -f compose.production.yaml --profile web logs --tail 100 web bff api
curl -i https://sentinela.seu-dominio.com/
curl -i https://sentinela.seu-dominio.com/api/session
```

**Checklist manual de aceitação:** HTML React em `/`, assets /assets, página /app com fallback SPA, GET /api/session retornando JSON, redirecionamento OIDC e callback válidos, cookie `Secure` em HTTPS, login/logout, envio de mensagem, upload de imagem e áudio, eventos SSE sem buffering, reinicialização de conversa, ausência de exposição direta do BFF e do banco, e webhook Evolution funcionando após a atualização. `/api/session` sem login deve retornar `authenticated: false`; `/auth/login` normalmente redireciona ao IdP.

Confira também a configuração de cookies, encaminhamento Host e limites de requisição no Cloudflare. Cloudflare Access, caso ativado, precisa ser compatível com os redirects do IdP. Evite substituir regras já existentes.

## Recuperação

Verifique primeiro os logs de `web`, `bff` e `api`, a resolução de `sentinela-bff` no Traefik e a rede `celo-network`; não reinicie a borda compartilhada como primeiro recurso. Para retornar à topologia anterior, faça rollback do código, mantendo os **mesmos volumes e nome Compose**; `docker compose down -v` destruiria dados. O script não executa mudanças no Tunnel automaticamente e não oferece rollback sem interrupção.

## Limites

- Apenas uma instância do BFF por padrão. Os limites em memória de rate-limit/SSE requerem datastore compartilhado para escalonamento horizontal.
- As redes Docker são isolamentos operacionais, não autorização criptográfica; não conecte containers não confiáveis à rede de borda.
- Este PR não configura efetivamente o Cloudflare Tunnel/IdP da VPS nem demonstra throughput. A CI avalia configuração; validação pública e OIDC real dependem do ambiente.

# Opt-in, migração e contrato Evolution API 2.3.7

## Semântica do ciclo de vida
- Estado inicial por `(instance,wid)`: `active=false`; mensagens são encerradas com `done` e `payload={}` sem resposta, presença, cota ou OpenAI.
- `Sentinela` (casefold e strip do texto completo): ativa e responde exatamente `Sentinela ativo. Envie a mensagem, imagem ou áudio suspeito. Para terminar, envie Encerrar.`; nova ativação após inatividade cria novo `session_id`, preservando o `user_id`.
- Enquanto ativo, texto, imagem, áudio e `/nova` seguem as mesmas regras já existentes.
- `Encerrar`: desativa, limpa `facts`, `absent`, `last_question` e `asked_questions`; responde exatamente `Sessão encerrada. Para iniciar novamente, envie Sentinela.`.
- `Sentinela` repetido enquanto ativo retorna a confirmação, sem resetar indevidamente o caso.
- Uma conversa após `Encerrar` permanece silenciosa até nova ativação, inclusive para `/nova` e mídia.

## Transação e recuperação
O worker chama `Store.gate(job)` imediatamente após reclamar um job com resposta vazia, antes de iniciar digitação, reservar cota, baixar mídia, transcrever ou invocar IA. O `gate` valida o job em `processing`, bloqueia a linha de inbox e a linha da sessão com `SELECT ... FOR UPDATE` e atualiza **na mesma transação** o estado e a resposta `ready` (ou `done` para silêncio). Falha no gate provoca rollback e retry, sem estado parcialmente ativado.

O worker mantém um advisory lock de sessão PostgreSQL durante a inicialização, a recuperação e o processamento, rejeitando uma segunda réplica. A ordem das mensagens do mesmo `instance,wid` continua protegida pelo filtro de jobs anteriores da fila. A deduplicação usa `UNIQUE(instance,message_id)`.

Na recuperação, `processing` volta a `pending`; uma resposta `ready` permanece entregável. Um envio iniciado (`sending`) vira `uncertain` após crash: a Evolution não fornece um contrato de idempotência de entrega que permita retentativas sem risco de duplicação. O sistema prefere não reenviar automaticamente em caso de incerteza.

## Atualização de banco existente
O schema `db/001_initial.sql` cria `active boolean NOT NULL DEFAULT false`. Ao iniciar, o worker executa migração idempotente `ALTER TABLE app.sessions ADD COLUMN IF NOT EXISTS active boolean NOT NULL DEFAULT false`, sem remover dados existentes. **Contatos anteriormente atendidos precisarão ativar o Sentinela** após o upgrade. Não rode `docker compose down -v` nem apague o banco.

## Evolution API
O contrato de `InstanceDto.webhook` da v2.3.7 contém `byEvents`, `base64`, `headers`, `url`, `enabled` e `events`. Para esta versão, o configurador envia `byEvents=false`, `base64=false`, `headers.apikey`, `MESSAGES_UPSERT`, `PRESENCE_UPDATE`; a URL é restrita e exige `--apply`.

Fonte da versão: https://github.com/EvolutionAPI/evolution-api/blob/2.3.7/src/api/dto/instance.dto.ts

Os nomes `webhookByEvents` e `webhookBase64` aparecem em outras documentações e versões; não são usados no corpo do webhook deste projeto.

## Nomes de instância Unicode
`Settings.evolution_instance` tem comprimento de 1 a 80 code points, com letras e dígitos Unicode mais `_` e `-`. Não aceita `/`, `..`, espaço ou caracteres especiais. O nome original é mantido no armazenamento/eventos; nas rotas HTTP o nome é percent-encoded por `urllib.parse.quote(..., safe="")`, inclusive `meu-número` → `meu-n%C3%BAmero`.

## Evidências e execução
CI: Python 3.15.2, Poetry 2.2.1, `poetry check --lock`, instalação com dependências travadas, pytest (incluindo PostgreSQL 18 descartável), Ruff, Mypy e build Docker. O Dockerfile exige `poetry.lock` em `COPY`; não o gera em build.

Os testes de PostgreSQL cobrem ativação, silêncio, encerramento, reativação, sessão persistida, isolamento, rollback e retry de gate, deduplicação, transições `ready/sending/uncertain` e exclusividade do worker. Testes unitários cobrem URL Unicode, comandos sem cota/IA e payload Evolution v2.3.7.

Limitação: não houve comunicação com uma instância Evolution real nem uso de chave OpenAI neste ambiente; os testes externos continuam necessários na VPS.

# Auditoria técnica — 2026-11-25/26

## Evidências verificadas
- GitHub Actions da main no SHA `19d6b553`: testes, lint, mypy e smoke import passaram.
- Contrato da API de mídia da Evolution: antes era enviado só o identificador; agora a solicitação preserva o envelope de mensagem criptografada (key + message). Integração real depende da versão da Evolution em uso.
- Agno: documentação de `PostgresDb`, `Agent.tool_call_limit`, `OpenAIChat.max_completion_tokens` e `retry_with_guidance` consultada. A recuperação guiada foi explicitamente desabilitada.
- Testes unitários do contrato de mídia, wrappers e falsos positivos de prompt injection incorporados ao workflow.

## Problemas corrigidos
1. **Mídia do WhatsApp:** o download era solicitado apenas com a chave da mensagem, sem a estrutura criptografada, potencialmente tornando imagens e áudios inutilizáveis. Envelope completo armazenado temporariamente em inbox; apagado no estado terminal.
2. **Mensagens efêmeras e view once:** suporte a wrappers conhecidos, até três níveis.
3. **Tentativas ocultas:** desativado `retry_with_guidance` do Agno além de `max_retries=0`.
4. **Falso positivo de injection:** trechos citados dentro de mensagens suspeitas deixam de ser bloqueados por regex sobre toda a entrada; o conteúdo continua não confiável e schema determinístico impede respostas arbitrárias.
5. **Entradas de mídia inválidas:** erro permanente passa a produzir uma mensagem segura em vez de repetir indefinidamente no limite de tentativas.
6. **Retenção:** exclusão periódica de eventos em estado terminal após sete dias e cotas após 31 dias.

## Limitações ainda presentes
- Não foi feito teste end-to-end com Evolution API e uma chave real da OpenAI. Contrato exato de envio de typing e obtenção de mídia depende da versão implantada.
- O orçamento contabiliza tentativas, não preço real, duração de áudio, tokens de imagem e provedor.
- Retenção automática das tabelas nativas do Agno ainda requer política operacional de privacidade.
- PostgreSQL usa novas conexões por operação; suficiente para MVP, mas será gargalo sob volume mais alto.
- O worker deve ter uma única réplica, por conta da ordenação por usuário e do contrato de envio at-most-once.
- A classificação é heurística e não possui avaliação estatística calibrada. O sistema não declara que um endereço ou mensagem é seguro.
- Não há limite real de duração da tarefa fora dos timeouts HTTP. As falhas de send após timeout permanecem com status `uncertain` para evitar duplicidade.
- A gestão de segredos, rate limit na borda, backup PostgreSQL e TLS devem ser configurados na VPS.

## Documentação consultada
- https://docs.agno.com/reference/storage/postgres
- https://docs.agno.com/reference/agents/agent
- https://docs.agno.com/reference/models/openai
- https://doc.evolution-api.com/
- https://www.python.org/downloads/

A CI é teste automatizado, não substitui testes de integração externa.

## Verificação das versões publicadas em 25/11/2026
| Tecnologia | Versão recente publicada | Compatibilidade declarada no projeto |
|---|---|---|
| Python | 3.15.2 | >=3.15,<3.16 |
| Agno | 3.2.1 | ==3.2.1 |
| OpenAI SDK | 3.59.0 | >=3.59,<4 (atualizado neste PR) |
| FastAPI | 0.165.0 | >=0.115,<1 |
| Pydantic | 2.14.4 | >=2.11,<3 |
| SQLAlchemy | 2.1.9 | >=2.0,<3, com extra asyncio |
| Psycopg | 3.3.9 | >=3.2,<4 |

Fontes: https://pypi.org/project/agno/ , https://pypi.org/project/openai/ , https://pypi.org/project/fastapi/ , https://pypi.org/project/pydantic/ , https://pypi.org/project/SQLAlchemy/ e https://pypi.org/project/psycopg/ .

**Limitação:** por ausência de um arquivo poetry.lock versionado, a resolução de dependências do Docker e da CI pode variar entre builds. O workflow deste PR testa a construção da imagem para detectar incompatibilidades, mas um lock continua recomendado para uma entrega reprodutível.

## Falha adicional identificada pela CI de imagem Docker
A execução 45734553679 detectou falta de `gcc` no estágio de build `python:3.15.2-slim`. Uma dependência transitiva do Poetry (`zstandard`) foi instalada a partir de código-fonte por não haver wheel adequada no momento do teste. A imagem agora instala `build-essential` **apenas no estágio de construção**, sem incluir o compilador na imagem de produção. A confirmação depende de novo build no HEAD do PR.

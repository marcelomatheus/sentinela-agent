# Respostas contextuais e isolamento de casos

## Diagnóstico da repetição

Anteriormente, o renderizador mostrava literalmente a classificação e até duas regras acionadas, com o mesmo texto em mensagens diferentes. Além disso, quando `continues_previous=true`, o mecanismo preservava `BANK` e `OTP` entre mensagens e repetia o risco `ALTO`. A continuidade é útil para complementar o mesmo golpe, mas não deve carregar indícios para uma mensagem sobre outro assunto.

## Estratégia aplicada

1. A extração estruturada Agno retorna `present`, `absent`, `continues_previous`, `in_scope` e agora `context_note` (até 160 caracteres). Isso reutiliza a chamada existente, sem criar outro agente gerador de respostas.
2. O novo campo é apenas uma observação textual neutra, não uma decisão. O código de domínio valida tamanho, caracteres, ausência de links/códigos/instruções e compatibilidade lexical com o texto da mensagem. Imagens sem legenda podem receber um resumo, mas não há garantia de correspondência sem validação de imagem.
3. As 12 regras, o cálculo do risco, as perguntas disponíveis e recomendações permanecem determinísticos. A resposta insere a observação validada como contexto conversacional; se inválida, retorna ao texto seguro preexistente.
4. A aplicação detecta início explícito de outro caso e mudança de cenário (`BANK`, `FAMILY`, `SHOP`, `PRIZE`, `JOB`, `INVESTMENT`, `DELIVERY`). Nesses casos, reinicia `session_id` e apaga fatos, ausências e perguntas, mesmo quando o modelo indicou continuidade equivocadamente.
5. Se o risco anterior já era alto e as regras acionadas permanecem idênticas, um acompanhamento recebe resposta concisa com a recomendação prática, sem relistar o diagnóstico técnico.

## Exemplos ilustrativos

**Primeira mensagem:** “Um banco pediu um código por SMS.”

> ⚠️ Pelo que você contou, o banco pediu um código por SMS. Isso pode ser golpe. Ligue para o banco pelos canais oficiais. Não informe códigos recebidos por SMS ou aplicativo.

**Acompanhamento do mesmo caso:** “Agora pediram outro código pelo aplicativo.”

> Entendi: o contato pediu outro código pelo aplicativo. Sobre esse caso, Ligue para o banco pelos canais oficiais.

**Outro assunto:** “Uma loja anunciou preço baixo e pediu adiantamento.”

> ⚠️ Pelo que você contou, uma loja anunciou preço baixo e pediu adiantamento. Isso pode ser golpe. Verifique a loja independentemente do anúncio.

As respostas são demonstrativas: a observação contextual depende do que a extração identificar, mas as orientações do motor de inferência não variam conforme a geração da IA.

## Segurança e limites

A frase contextual pode variar, mas não determina o risco. O filtro local recusa URLs, instruções, segredos/identificadores longos, formatação de markup e observações sem relação textual com o conteúdo. Não é uma garantia de fidelidade semântica perfeita; a avaliação com dados reais rotulados continua necessária. A aplicação não copia automaticamente o conteúdo integral da mensagem para a resposta. Nenhum histórico de mensagens foi introduzido no prompt ou no armazenamento; apenas fatos, pergunta anterior e o próprio conteúdo sob análise.

## Testes de regressão

`tests/test_contextual_replies.py` verifica: duas mensagens com as mesmas regras gerando respostas distintas; troca de golpe apesar do marcador de continuidade incorreto; novo caso explícito de mesma categoria; recusa de resumos inseguros; preservação de risco e orientação; resposta inconclusiva sem afirmar legitimidade.

A CI deve executar testes PostgreSQL descartável, Ruff, Mypy, validação do lock e build Docker. Testes de concordância semântica e produtividade com modelos OpenAI reais não fazem parte da CI e devem ser feitos em ambiente autorizado.

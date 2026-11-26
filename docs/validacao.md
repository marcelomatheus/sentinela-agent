# Validação

Esta branch recompõe o setup original a partir dos arquivos e artefatos disponíveis. Não é uma cópia binária verificada do ZIP anterior.

Os testes incluídos devem ser executados pela CI. Nenhum resultado de teste do ZIP anterior é atribuído automaticamente a esta revisão.

Pendências: resolução de dependências e poetry.lock; compatibilidade de Python/Agno e SDKs; execução Docker/PostgreSQL; testes reais de webhook, presença, mídia e modelos OpenAI; evidências acadêmicas reais. O worker é projetado para uma única réplica. A consulta de reputação opcional usa apenas a origem do URL, não garante segurança nem cobertura de URLs específicas. Os pesos/regras são heurísticos e não representam validação científica.

Não publique mensagens, mídias, credenciais ou WIDs reais nas evidências. Configure retenção e exclusão de dados antes de uso real.

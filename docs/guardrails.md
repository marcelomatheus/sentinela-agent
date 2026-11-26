# Guardrails — Sentinela

## Threat model
Messages, captions, screenshots and transcriptions are untrusted data. Webhook authentication is a trust boundary: anyone who controls Evolution or its shared key can impersonate senders. Deploy over HTTPS and restrict network access; keep the key private. LIDs remain separate from telephone identities until verified mapping is implemented. No tool can read other users or execute arbitrary commands.

## Layers
- Domain: static identity/help, heuristic detection of direct injection, bounded input, scope refusal, strict enums and deterministic rendering. Regex is defense in depth, not comprehensive detection; may reject legitimate quoted evidence. Never relay arbitrary model output.
- Application: out-of-scope or inconsistent observations preserve session; max three distinct clarifying questions per case, no tools and no recursion. Fresh Agno instances, history disabled, explicit UUIDs sourced only from PostgreSQL. Agno DB stores question-selection facts only; extraction does not attach persistent storage.
- Persistence: atomic per-sender and global UTC-day reservations before analysis, including retries. Defaults 20 and 200 attempts/day. Quota cannot be reset with /nova. Every attempt can invoke at most extraction, optional question selection, and optional transcription under current flow. No SDK/agent automatic retries; job retries remain bounded at three.
- Provider: 768 completion tokens per chat call, 25s HTTP timeout, input 4000 characters and audio 500 KB. Existing image resizing applies. These are **not an exact monetary cap**; image tokens, reasoning, audio duration and provider billing differ. HTTP timeout is not a hard wall-clock deadline. Configure separate provider-side limits/alerts.
- Output: only domain templates, enum facts and allowlisted question IDs reach WhatsApp. No raw model prose, credentials, identifiers or retrieved history.

## Deploy
Existing volumes: worker applies an idempotent schema migration at startup (requires DDL permission). Keep one worker replica. Defaults in .env.example. Daily quota rows retain sender identity; apply retention appropriate to deployment.

## Validation
Unit tests exercise identity, direct injection, input bounds, scope, fact conflicts, fabricated reputation, question loops, reset and session independence. PostgreSQL test exercises quota persistence and ownership. Real-model adversarial evaluation, token billing and deployment remain pending; prompt injection classification is probabilistic and cannot guarantee detection. No live user data used.

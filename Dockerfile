FROM python:3.15.2-slim AS build
ENV POETRY_VERSION=2.2.1 POETRY_NO_INTERACTION=1 POETRY_VIRTUALENVS_IN_PROJECT=true
WORKDIR /app
RUN pip install --no-cache-dir "poetry==$POETRY_VERSION"
COPY pyproject.toml poetry.lock* ./
# O lock deve ser gerado e versionado antes de um deploy reproduzível.
RUN poetry install --only main --no-root
COPY src ./src
COPY scripts ./scripts
RUN poetry install --only main
FROM python:3.15.2-slim
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 AGNO_TELEMETRY=false
WORKDIR /app
RUN groupadd --system app && useradd --system --gid app --no-create-home app
COPY --from=build /app /app
USER app
EXPOSE 8080
CMD ["uvicorn", "sentinela.interfaces.http:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]

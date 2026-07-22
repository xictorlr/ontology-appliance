FROM python:3.14-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PORT=8080 \
    OA_ENV=production \
    OA_ARTIFACT_DIR=/app/semantic/artifacts \
    OA_LAST_VALID_PATH=/tmp/ontology-appliance/last-valid.trig

WORKDIR /app

COPY services/semantic-gateway/pyproject.toml /app/services/semantic-gateway/pyproject.toml
COPY services/semantic-gateway/uv.lock /app/services/semantic-gateway/uv.lock
COPY services/semantic-gateway/src /app/services/semantic-gateway/src
WORKDIR /app/services/semantic-gateway
RUN pip install --no-cache-dir "uv==0.11.30" \
    && uv sync --frozen --no-dev --extra firebase --extra vertex

ENV PATH="/app/services/semantic-gateway/.venv/bin:${PATH}"

COPY semantic/artifacts /app/semantic/artifacts
WORKDIR /app

RUN chmod -R a+rX /app/services/semantic-gateway/src /app/semantic/artifacts \
    && useradd --create-home --uid 10001 appuser \
    && mkdir -p /tmp/ontology-appliance \
    && chown -R appuser:appuser /tmp/ontology-appliance
USER appuser

EXPOSE 8080
CMD ["sh", "-c", "uvicorn ontology_appliance_gateway.main:app --app-dir /app/services/semantic-gateway/src --host 0.0.0.0 --port ${PORT}"]

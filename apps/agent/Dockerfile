FROM ghcr.io/astral-sh/uv:0.11.11 AS uv
FROM python:3.12.13-slim
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY apps/agent/pyproject.toml apps/agent/uv.lock ./
RUN uv sync --frozen --no-dev
COPY apps/agent/src ./src
COPY agents ./agents
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH=/app/src PYTHONUNBUFFERED=1
RUN useradd --uid 10001 --create-home parcel && mkdir -p /data/telemetry && chown 10001:10001 /data/telemetry
USER parcel
EXPOSE 8000
CMD ["uvicorn","parceldesk.main:app","--host","0.0.0.0","--port","8000","--no-access-log"]

FROM python:3.12-slim-bookworm AS builder

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ src/
COPY scripts/install/ scripts/install/

RUN pip install --no-cache-dir uv && \
    uv pip install --system ".[server]"

# Runtime
FROM python:3.12-slim-bookworm

COPY --from=builder /usr/local /usr/local
COPY --from=builder /app /app
WORKDIR /app

ENV OLLAMA_HOST=http://host.docker.internal:11434

EXPOSE 8000

ENTRYPOINT ["grandpa"]
CMD ["serve", "--engine", "ollama", "--host", "0.0.0.0", "--port", "8000", "--allow-insecure-bind"]

# Grandpa home server (P2): `grandpa server --headless` for the Pironman /
# Raspberry Pi 5 (linux/arm64). Builds for amd64 too.
#
#   docker build -f docker/headless.Dockerfile -t grandpa-headless .
#   docker run -d --name grandpa -p 8000:8000 -v grandpa-data:/data \
#     -e GRANDPA_PC_URL=http://192.168.1.20:8000 \
#     --env-file grandpa.env grandpa-headless
#
# grandpa.env holds GRANDPA_PC_TOKEN=gp_dev_... (from `grandpa server pair`).
# No secrets are baked into the image.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    GRANDPA_HOME=/data

WORKDIR /app
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY src ./src
RUN pip install ".[server]" \
    && useradd --create-home --uid 10001 grandpa \
    && mkdir -p /data && chown grandpa:grandpa /data

USER grandpa
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=60s --timeout=5s --start-period=30s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"
CMD ["python", "-m", "grandpa", "server", "--headless", "--host", "0.0.0.0", "--port", "8000"]

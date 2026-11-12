# syntax=docker/dockerfile:1.7
#
# Citewell image. CPU-only PyTorch keeps it reasonably small (~1.5 GB with models
# support). Build without local models (hash embedder only, for demos/CI):
#   docker build --build-arg WITH_MODELS=false --build-arg WITH_OCR=false -t citewell:slim .
# OCR for scanned PDFs (CITEWELL_OCR=auto) needs tesseract with Turkish data; WITH_OCR=false leaves it out.

ARG PYTHON_VERSION=3.12

FROM ghcr.io/astral-sh/uv:0.13.7 AS uv

# --------------------------------------------------------------------------- builder
FROM python:${PYTHON_VERSION}-slim AS builder
COPY --from=uv /uv /usr/local/bin/uv
ARG WITH_MODELS=true
ARG WITH_OCR=true
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH
WORKDIR /src

RUN uv venv /opt/venv
COPY pyproject.toml uv.lock README.md LICENSE ./

# Install locked dependencies. PyTorch comes from the CPU wheel index at the locked
# version; CUDA wheels from PyPI are filtered out.
RUN --mount=type=cache,target=/root/.cache/uv \
    set -eu; \
    extra=""; \
    if [ "$WITH_MODELS" = "true" ]; then extra="--extra models"; fi; \
    if [ "$WITH_OCR" = "true" ]; then extra="$extra --extra ocr"; fi; \
    uv export --frozen --no-dev --no-emit-project --no-hashes $extra -o /tmp/requirements.txt; \
    if [ "$WITH_MODELS" = "true" ]; then \
      torch_version="$(grep -E '^torch==' /tmp/requirements.txt | cut -d'=' -f3 | cut -d' ' -f1)"; \
      uv pip install --index-url https://download.pytorch.org/whl/cpu "torch==${torch_version}"; \
    fi; \
    grep -vE '^(torch|triton|nvidia-|cuda-)' /tmp/requirements.txt > /tmp/requirements.notorch.txt; \
    uv pip install -r /tmp/requirements.notorch.txt

COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv uv pip install --no-deps .

# --------------------------------------------------------------------------- runtime
FROM python:${PYTHON_VERSION}-slim AS runtime
LABEL org.opencontainers.image.title="citewell" \
      org.opencontainers.image.description="Citation-grounded document memory for AI assistants. Offline, MCP-native, Turkish-ready." \
      org.opencontainers.image.source="https://github.com/omerozkilic/citewell" \
      org.opencontainers.image.licenses="MIT"

ARG WITH_OCR=true
# Pick up Debian security fixes published after the base image was built; tesseract is for OCR.
RUN apt-get update \
 && apt-get upgrade -y --no-install-recommends \
 && if [ "$WITH_OCR" = "true" ]; then \
      apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-tur tesseract-ocr-eng; \
    fi \
 && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 citewell \
 && mkdir -p /models /data \
 && chown citewell:citewell /models /data

COPY --from=builder /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/models \
    CITEWELL_HOST=0.0.0.0 \
    CITEWELL_PORT=8000

USER citewell
WORKDIR /home/citewell
VOLUME ["/models"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)" || exit 1

ENTRYPOINT ["citewell"]
CMD ["serve", "--init"]

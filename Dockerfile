FROM golang:1.25-bookworm AS go

FROM python:3.13-slim-bookworm

ARG TARGETARCH
ARG TFLINT_VERSION=0.56.0
ARG CONFTEST_VERSION=0.57.0
ARG OPA_VERSION=0.70.0
ARG IAC_EVAL_REPO=https://github.com/autoiac-project/iac-eval.git

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PATH="/usr/local/go/bin:${PATH}" \
    BYPASS_TOOL_CONSENT=true \
    TF_INPUT=0

COPY --from=go /usr/local/go /usr/local/go

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        git \
        gnupg \
        make \
        openssh-client \
        unzip; \
    install -m 0755 -d /etc/apt/keyrings; \
    curl -fsSL https://apt.releases.hashicorp.com/gpg | gpg --dearmor -o /etc/apt/keyrings/hashicorp.gpg; \
    . /etc/os-release; \
    echo "deb [signed-by=/etc/apt/keyrings/hashicorp.gpg] https://apt.releases.hashicorp.com ${VERSION_CODENAME} main" > /etc/apt/sources.list.d/hashicorp.list; \
    curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg; \
    chmod a+r /etc/apt/keyrings/docker.gpg; \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian ${VERSION_CODENAME} stable" > /etc/apt/sources.list.d/docker.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        docker-ce-cli \
        terraform; \
    rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    case "${TARGETARCH:-amd64}" in \
        amd64) cli_arch="amd64" ;; \
        arm64) cli_arch="arm64" ;; \
        *) echo "Unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    curl -fsSLo /tmp/tflint.zip "https://github.com/terraform-linters/tflint/releases/download/v${TFLINT_VERSION}/tflint_linux_${cli_arch}.zip"; \
    unzip -q /tmp/tflint.zip -d /tmp/tflint; \
    install -m 0755 /tmp/tflint/tflint /usr/local/bin/tflint; \
    rm -rf /tmp/tflint /tmp/tflint.zip

RUN set -eux; \
    case "${TARGETARCH:-amd64}" in \
        amd64) cli_arch="x86_64" ;; \
        arm64) cli_arch="arm64" ;; \
        *) echo "Unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    curl -fsSLo /tmp/conftest.tar.gz "https://github.com/open-policy-agent/conftest/releases/download/v${CONFTEST_VERSION}/conftest_${CONFTEST_VERSION}_Linux_${cli_arch}.tar.gz"; \
    tar -xzf /tmp/conftest.tar.gz -C /tmp conftest; \
    install -m 0755 /tmp/conftest /usr/local/bin/conftest; \
    rm -f /tmp/conftest /tmp/conftest.tar.gz

RUN set -eux; \
    curl -fsSL https://raw.githubusercontent.com/infracost/infracost/master/scripts/install.sh | sh

# ── rtk (optional command proxy — reduces LLM token usage) ──────────────────
ARG RTK_VERSION=0.39.0
RUN set -eux; \
    case "${TARGETARCH:-amd64}" in \
        amd64) rtk_triple="x86_64-unknown-linux-musl" ;; \
        arm64) rtk_triple="aarch64-unknown-linux-gnu" ;; \
        *) echo "Unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    curl -fsSLo /tmp/rtk.tar.gz \
        "https://github.com/rtk-ai/rtk/releases/download/v${RTK_VERSION}/rtk-${rtk_triple}.tar.gz"; \
    tar -xzf /tmp/rtk.tar.gz -C /tmp rtk; \
    install -m 0755 /tmp/rtk /usr/local/bin/rtk; \
    rm -f /tmp/rtk /tmp/rtk.tar.gz

# ── OPA (Open Policy Agent) ──────────────────────────────────────────────────
RUN set -eux; \
    case "${TARGETARCH:-amd64}" in \
        amd64) opa_arch="linux_amd64_static" ;; \
        arm64) opa_arch="linux_arm64_static" ;; \
        *) echo "Unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    curl -fsSLo /usr/local/bin/opa \
        "https://github.com/open-policy-agent/opa/releases/download/v${OPA_VERSION}/opa_${opa_arch}"; \
    chmod +x /usr/local/bin/opa

# ── iac-eval repo (Rego policies + dataset cache) ───────────────────────────
RUN git clone --depth=1 ${IAC_EVAL_REPO} /opt/iac-eval
ENV IAC_EVAL_DIR=/opt/iac-eval

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --upgrade pip && \
    python -m pip install -r requirements.txt

# Download and cache iac-eval dataset inside image (uses HF network at build time)
# HF_TOKEN build-arg is optional (increases rate limits for unauthenticated pulls)
ARG HF_TOKEN=""
RUN HF_DATASETS_CACHE=/opt/iac-eval/.hf_cache \
    HF_TOKEN=${HF_TOKEN} \
    python -c "\
from datasets import load_dataset; \
load_dataset('autoiac-project/iac-eval', 'default', cache_dir='/opt/iac-eval/.hf_cache'); \
load_dataset('autoiac-project/iac-eval', 'quick_test', cache_dir='/opt/iac-eval/.hf_cache')" \
    || echo "[warn] iac-eval dataset pre-cache failed — will fall back to live HF download at runtime"

COPY . .

CMD ["python", "main.py"]

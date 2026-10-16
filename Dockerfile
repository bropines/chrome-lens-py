# syntax=docker/dockerfile:1
#
# lens_scan as a daemon:
#
#   docker run -d -p 127.0.0.1:8765:8765 -e LENS_TOKEN=change-me ghcr.io/bropines/chrome-lens-py
#   curl -H "Authorization: Bearer change-me" ...   (POST /v1/ocr, GET /health)
#
# LENS_TOKEN is required. The daemon binds 0.0.0.0 inside the container, and the
# CLI refuses to listen on a non-loopback address without a token, because
# anyone who could reach it could spend your API key on Google requests.
# Publish the port on 127.0.0.1 unless you mean to expose it.
#
# Build from PyPI:   docker build --build-arg VERSION=3.5.3 -t lens-scan .
# Build from source: python -m build --wheel && docker build -t lens-scan .
# (a wheel in ./dist is installed in preference to PyPI.)

FROM python:3.12-slim

# Only needed when there is no wheel to install. With one in ./dist, VERSION is
# just checked against it.
ARG VERSION

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# Dockerfile is named only so the COPY always has one source that exists; the
# wheels are optional (.dockerignore lets through dist/*.whl and nothing else).
COPY Dockerfile dist/*.whl /wheels/

# A wheel from this checkout wins over PyPI: the CI check must test the code it
# just built, and PyPI may already hold the same version number.
RUN set -eu; \
    if ls /wheels/*.whl >/dev/null 2>&1; then \
        pip install /wheels/*.whl; \
    else \
        test -n "${VERSION:-}" || { echo "pass --build-arg VERSION=<release version> (no wheel in ./dist)" >&2; exit 1; }; \
        pip install "chrome-lens-py==${VERSION}"; \
    fi; \
    if [ -n "${VERSION:-}" ]; then \
        installed=$(pip show chrome-lens-py | sed -n 's/^Version: //p'); \
        [ "$installed" = "$VERSION" ] || { echo "installed $installed, expected $VERSION" >&2; exit 1; }; \
    fi; \
    rm -rf /wheels

RUN useradd --create-home --uid 10001 lens
USER lens
WORKDIR /home/lens

EXPOSE 8765

# /health needs no token. There is no curl in the slim image, so ask Python.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/health', timeout=4).status == 200 else 1)"]

# Shell form on purpose: the token comes from the environment and must not be
# baked into the image. `exec` keeps lens_scan as PID 1 so it gets SIGTERM.
# Extra `docker run` arguments are appended (e.g. --allow-origin https://...).
ENTRYPOINT ["sh", "-c", "exec lens_scan --serve --host 0.0.0.0 --port 8765 --token \"${LENS_TOKEN:?set LENS_TOKEN (the bearer token clients must send)}\" \"$@\"", "lens_scan"]

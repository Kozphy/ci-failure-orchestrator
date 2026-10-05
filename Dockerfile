# One image for both roles: the API (default CMD) and the worker (override the command).
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# No system packages: the foundation pipeline the server runs does not shell out to git.
# fix-repo (which does) is a CLI workflow and is not exposed by this image.
WORKDIR /app
COPY pyproject.toml README.md ./
# Dependencies are installed against an empty package so this layer survives code edits.
RUN mkdir ci_failure_orchestrator && touch ci_failure_orchestrator/__init__.py \
    && pip install ".[server]" \
    && pip uninstall -y ci-failure-orchestrator \
    && rm -rf ci_failure_orchestrator build ./*.egg-info
COPY ci_failure_orchestrator ./ci_failure_orchestrator
RUN pip install --no-deps . && rm -rf build ./*.egg-info

RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data/artifacts \
    && chown -R app:app /data
USER app

ENV CFO_ARTIFACTS_ROOT=/data/artifacts
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"

CMD ["uvicorn", "ci_failure_orchestrator.server.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

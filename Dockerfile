# RackWatch API + dashboard image.
# Slim Python, no Rust, no Node. Templates and static files are copied in.
# The container expects /data for SQLite and (optionally) the Docker socket.

FROM python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    RACKWATCH_HOST=0.0.0.0 \
    RACKWATCH_PORT=8080

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --require-hashes --no-deps -r requirements.txt

COPY app ./app
COPY scripts ./scripts

RUN useradd --create-home --uid 10001 rackwatch \
    && mkdir -p /data \
    && chown -R rackwatch:rackwatch /app /data

# The process needs the Docker socket; we stay root-capable of connecting
# to a mounted socket. Drop extra caps in compose if you do not restart
# containers from this box.
USER rackwatch

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=4)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]

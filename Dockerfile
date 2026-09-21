FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py pensum.json ./

RUN useradd --create-home --uid 10001 appuser && \
    mkdir -p /data && chown appuser:appuser /data

VOLUME /data
USER appuser

ENV PORT=5000 \
    DISK_CACHE_PATH=/data/soppquiz_cache.json \
    IMAGE_SOURCE=artsobs
EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/healthz', timeout=3)"

CMD ["python", "app.py"]
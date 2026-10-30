FROM mcr.microsoft.com/playwright/python:v1.64.1-noble

USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg xvfb xauth fonts-dejavu-core tini ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml requirements.lock ./
COPY cloudbrowser ./cloudbrowser
RUN python -m pip install --no-cache-dir -r requirements.lock \
    && python -m pip install --no-cache-dir --no-deps .
COPY scripts /app/scripts
RUN chmod 755 /app/scripts/entrypoint.sh && mkdir -p /data && chown pwuser:pwuser /data
ENV CLOUDBROWSER_DATA_DIR=/data \
    CLOUDBROWSER_BIND_HOST=0.0.0.0 \
    PYTHONUNBUFFERED=1
USER pwuser
EXPOSE 8000
ENTRYPOINT ["tini", "--", "/app/scripts/entrypoint.sh"]
CMD ["serve"]

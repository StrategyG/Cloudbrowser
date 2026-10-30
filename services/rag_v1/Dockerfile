FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
    HF_HUB_DISABLE_TELEMETRY=1 DO_NOT_TRACK=1 HF_HOME=/tmp/hf
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py ./app.py
RUN useradd -u 10001 -m rag && mkdir -p /models && chown rag:rag /models
USER rag
EXPOSE 8090
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8090", "--workers", "1", "--no-access-log"]

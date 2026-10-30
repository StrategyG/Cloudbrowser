FROM python:3.13-slim-trixie
ARG GODOT_VERSION=4.7.2
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 GODOT_BIN=/usr/local/bin/godot LIBGL_ALWAYS_SOFTWARE=1
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl unzip ffmpeg xvfb xauth libgl1 libgl1-mesa-dri libx11-6 libxcursor1 libxrandr2 libxi6 libasound2t64 && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL --retry 3 --max-time 180 "https://github.com/godotengine/godot/releases/download/${GODOT_VERSION}-stable/Godot_v${GODOT_VERSION}-stable_linux.x86_64.zip" -o /tmp/godot.zip && unzip -q /tmp/godot.zip -d /tmp/godot && install -m 0755 "/tmp/godot/Godot_v${GODOT_VERSION}-stable_linux.x86_64" /usr/local/bin/godot && rm -rf /tmp/godot /tmp/godot.zip && godot --version
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY cloudbrowser/ cloudbrowser/
COPY godot/ godot/
COPY web/ web/
RUN useradd -m -u 10001 studio && mkdir /data && chown studio:studio /data
USER studio
CMD ["uvicorn","cloudbrowser.api:app","--host","0.0.0.0","--port","8085"]

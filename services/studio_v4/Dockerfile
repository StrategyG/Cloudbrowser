# Godot 4.7.2 stable (not the 4.8 beta) is the primary animation/render engine.
# Blender is currently retained only for skinning/rig authoring.
FROM python:3.13-slim-trixie
ARG GODOT_VERSION=4.7.2
ARG GODOT_SHA256=cadd3204e728a35d3f13adb7fd0d7902636b79f6b95c40c265eb73b6c35329e4
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 STUDIO_DATA_ROOT=/app/workspace \
    GODOT_BIN=/usr/local/bin/godot BLENDER_BIN=blender FFMPEG_BIN=ffmpeg FFPROBE_BIN=ffprobe \
    XVFB_BIN=xvfb-run LIBGL_ALWAYS_SOFTWARE=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl unzip blender ffmpeg xvfb xauth \
    libgl1 libgl1-mesa-dri libx11-6 libxcursor1 libxrandr2 libxi6 libasound2t64 \
    && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL --retry 3 --max-time 180 \
      "https://github.com/godotengine/godot-builds/releases/download/${GODOT_VERSION}-stable/Godot_v${GODOT_VERSION}-stable_linux.x86_64.zip" \
      -o /tmp/godot.zip \
    && echo "${GODOT_SHA256}  /tmp/godot.zip" | sha256sum -c - \
    && unzip -q /tmp/godot.zip -d /tmp/godot \
    && install -m 0755 "/tmp/godot/Godot_v${GODOT_VERSION}-stable_linux.x86_64" /usr/local/bin/godot \
    && rm -rf /tmp/godot /tmp/godot.zip \
    && godot --version
WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
COPY studio studio
COPY workers workers
COPY godot_project godot_project
COPY web web
RUN useradd --create-home --uid 10001 studio && mkdir -p /app/workspace && chown studio:studio /app/workspace
USER studio
EXPOSE 8000
CMD ["uvicorn","studio.api:app","--host","0.0.0.0","--port","8000"]

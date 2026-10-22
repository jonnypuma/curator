FROM debian:bookworm-slim AS dovi

ARG TARGETARCH
ARG DOVI_VERSION=2.1.2

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /tmp/dovi
RUN set -eux; \
    arch="${TARGETARCH:-$(dpkg --print-architecture)}"; \
    case "$arch" in \
      amd64) DOVI_ARCH=x86_64-unknown-linux-musl ;; \
      arm64) DOVI_ARCH=aarch64-unknown-linux-musl ;; \
      *) echo "Unsupported architecture: $arch (need amd64 or arm64)" >&2; exit 1 ;; \
    esac; \
    base="https://github.com/quietvoid/dovi_tool/releases/download/${DOVI_VERSION}"; \
    file="dovi_tool-${DOVI_VERSION}-${DOVI_ARCH}.tar.gz"; \
    curl -fsSL -o "$file" "$base/$file"; \
    curl -fsSL -o "$file.sha256" "$base/$file.sha256"; \
    sha256sum "$file" | cut -d' ' -f1 > actual.sha256; \
    cut -d' ' -f1 "$file.sha256" > expected.sha256; \
    cmp -s actual.sha256 expected.sha256; \
    tar -xzf "$file"; \
    install -m 0755 dovi_tool /usr/local/bin/dovi_tool


FROM python:3.11-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/tmp \
    CMM_PORT=4455

# OCR for picture subtitles (VobSub / PGS sync). Space separated tesseract language names;
# override with `build: args: TESSERACT_LANGS: "eng nor"` in docker-compose.yml. English is
# always installed because tesseract depends on it.
ARG TESSERACT_LANGS="eng nor swe dan fin deu fra spa ita nld por pol"

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
        xz-utils \
        flac \
        ffmpeg \
        libbluray2 \
        libdvdread8 \
        mkvtoolnix \
        tesseract-ocr \
        $(for lang in $TESSERACT_LANGS; do printf 'tesseract-ocr-%s ' "$lang"; done) \
        cuetools \
        shntool \
        libpq5 \
        libchromaprint-tools \
        gosu \
        passwd \
        tzdata \
        postgresql-client \
    && curl -fsSL -o /tmp/rsgain.tar.xz https://github.com/complexlogic/rsgain/releases/download/v3.6/rsgain-3.6-Linux.tar.xz \
    && mkdir -p /tmp/rsgain \
    && tar -xJf /tmp/rsgain.tar.xz -C /tmp/rsgain \
    && find /tmp/rsgain -type f -name rsgain -exec cp {} /usr/local/bin/rsgain \; \
    && chmod 755 /usr/local/bin/rsgain \
    && rm -rf /tmp/rsgain /tmp/rsgain.tar.xz \
    && curl -fsSL -o /tmp/repo-mediaarea.deb https://mediaarea.net/repo/deb/repo-mediaarea_1.0-25_all.deb \
    && dpkg -i /tmp/repo-mediaarea.deb \
    && apt-get update \
    && apt-get install -y --no-install-recommends mediainfo \
    && rm -rf /var/lib/apt/lists/* /tmp/repo-mediaarea.deb \
    && groupadd -g 1000 app \
    && useradd -u 1000 -g app -d /tmp -M app

# yt-dlp downloads trailers and theme songs from YouTube. YouTube changes often and an old yt-dlp stops
# working, so this is its own layer: it takes the newest release when the image is built. To refresh it alone,
# build with `--build-arg YTDLP_REFRESH=<any new value>`; to fix a release, use `--build-arg YTDLP_VERSION=2026.01.31`.
ARG YTDLP_VERSION=latest
ARG YTDLP_REFRESH=0
RUN set -eux; \
    if [ "$YTDLP_VERSION" = "latest" ]; then url="https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp"; \
    else url="https://github.com/yt-dlp/yt-dlp/releases/download/${YTDLP_VERSION}/yt-dlp"; fi; \
    curl -fsSL -o /usr/local/bin/yt-dlp "$url"; \
    chmod 755 /usr/local/bin/yt-dlp; \
    echo "yt-dlp $(/usr/local/bin/yt-dlp --version) (refresh ${YTDLP_REFRESH})"

# alass: automatic subtitle sync. The release is a static x86-64 binary; on other CPUs the
# image builds without it and the sync window hides the Automatic button.
ARG ALASS_VERSION=2.0.0
RUN if [ "$(dpkg --print-architecture)" = "amd64" ]; then \
        curl -fsSL -o /usr/local/bin/alass "https://github.com/kaegi/alass/releases/download/v${ALASS_VERSION}/alass-linux64" \
        && chmod 755 /usr/local/bin/alass \
        && /usr/local/bin/alass --version; \
    else echo "alass has no build for this CPU; automatic subtitle sync is off"; fi

COPY --from=dovi /usr/local/bin/dovi_tool /usr/local/bin/dovi_tool

# yt-dlp needs a JavaScript runtime to read YouTube since 2025.11.12. Deno is the one it uses without any setting.
COPY --from=denoland/deno:bin /deno /usr/local/bin/deno

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --chmod keeps files readable and directories searchable in this layer.
# A later "chmod -R /app" would copy every file into a new layer and is what made rebuilds slow.
COPY --chmod=755 . .
RUN sed -i 's/\r$//' /app/entrypoint.sh \
    && mkdir -p /config /cache /data /music /movies /tv

EXPOSE 4455

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${CMM_PORT}/api/v1/health" || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${CMM_PORT} --workers 1 --proxy-headers --log-level info"]

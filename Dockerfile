FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY --from=mwader/static-ffmpeg:7.1 /ffmpeg /usr/local/bin/
COPY --from=mwader/static-ffmpeg:7.1 /ffprobe /usr/local/bin/

RUN apt-get update && apt-get install -y --no-install-recommends libopus0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/
RUN uv pip install --system --only-binary :all: -r requirements.txt

COPY *.wav /app/
COPY scripts/ /app/scripts/
COPY alembic.ini /app/
COPY migrations/ /app/migrations/
COPY raid_migrations/ /app/raid_migrations/
COPY roboToald/ /app/roboToald/
COPY batphone.py /app/

CMD ["python", "-u", "./batphone.py"]

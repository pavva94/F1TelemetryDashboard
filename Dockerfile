FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8000
ENV FASTF1_CACHE_DIR=/app/.fastf1-cache
ENV SEASON_ANALYSIS_SEED_DIR=/app/season-cache-seed

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY frontend ./frontend
COPY season-cache-seed ./season-cache-seed

RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["fastf1-lapdiff-web"]


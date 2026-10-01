FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATABASE_PATH=/data/bunker.sqlite3
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock && useradd --uid 10001 --create-home bunker && mkdir -p /data && chown bunker:bunker /data
COPY --chown=bunker:bunker bunker ./bunker
CMD ["python", "-m", "bunker.bot.entrypoint"]

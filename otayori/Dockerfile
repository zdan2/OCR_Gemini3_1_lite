# おたより工房をコンテナで動かす。compose.yaml から作られる。
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OTAYORI_DATA=/app/data \
    OTAYORI_ENV_FILE=/app/data/.env

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py ./
COPY static ./static
COPY prompts ./prompts

EXPOSE 8787
CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8787", "--no-open"]

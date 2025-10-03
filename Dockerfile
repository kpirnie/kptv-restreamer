FROM python:3.12-alpine AS builder

WORKDIR /app

RUN apk add --no-cache gcc musl-dev

COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install --no-cache-dir --user -r requirements.txt

FROM python:3.12-alpine

WORKDIR /app

RUN apk add --no-cache curl && \
    adduser -D -s /bin/false appuser

COPY --from=builder /root/.local /home/appuser/.local

COPY app/ ./app/

RUN mkdir -p /app/config && \
    chown -R appuser:appuser /app

USER appuser

ENV PATH=/home/appuser/.local/bin:$PATH
ENV PYTHONPATH=/app

EXPOSE 8080

CMD ["python", "-m", "app.main", "--config", "/app/config/config.yaml"]
FROM docker.io/library/python:3.12-alpine AS builder

WORKDIR /app

# Fix DNS and use multiple mirrors with proper permissions
RUN echo "nameserver 8.8.8.8" > /etc/resolv.conf && \
    echo "nameserver 1.1.1.1" >> /etc/resolv.conf && \
    apk add --no-cache gcc musl-dev || \
    (sleep 2 && apk add --no-cache gcc musl-dev) || \
    (sleep 5 && apk add --no-cache gcc musl-dev)

COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install --no-cache-dir --user -r requirements.txt

FROM docker.io/library/python:3.12-alpine

WORKDIR /app

RUN echo "nameserver 8.8.8.8" > /etc/resolv.conf && \
    echo "nameserver 1.1.1.1" >> /etc/resolv.conf && \
    apk add --no-cache curl || \
    (sleep 2 && apk add --no-cache curl) || \
    (sleep 5 && apk add --no-cache curl) && \
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
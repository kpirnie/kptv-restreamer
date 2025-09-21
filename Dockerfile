# Build stage
FROM python:3.12-alpine AS builder

WORKDIR /app

# Install build dependencies
RUN apk add --no-cache gcc musl-dev

# Copy and install requirements
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Production stage
FROM python:3.12-alpine

WORKDIR /app

# Install only runtime dependencies
RUN apk add --no-cache curl && \
    adduser -D -s /bin/false appuser

# Copy Python packages from builder
COPY --from=builder /root/.local /home/appuser/.local

# Copy application
COPY restreamer.py .

# Create config directory
RUN mkdir -p /app/config && \
    chown -R appuser:appuser /app

USER appuser

# Make sure scripts in .local are usable
ENV PATH=/home/appuser/.local/bin:$PATH

EXPOSE 8080

CMD ["python", "restreamer.py", "--config", "/app/config/config.yaml"]
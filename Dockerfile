# Multi-stage Dockerfile for Entropy

# Stage 1: Build React dashboard
FROM node:20-alpine AS dashboard-builder
WORKDIR /app/dashboard
COPY dashboard/package.json dashboard/package-lock.json* ./
RUN npm install
COPY dashboard/ ./
RUN npm run build

# Stage 2: Python application
FROM python:3.11-slim

WORKDIR /app

# System deps for git analysis
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

# Copy app code
COPY entropy/ ./entropy/
COPY entropy.toml.example ./entropy.toml.example

# Copy built dashboard
COPY --from=dashboard-builder /app/dashboard/dist ./dashboard/dist

# Expose API port
EXPOSE 8000

# Default command: run the API server
CMD ["uvicorn", "entropy.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

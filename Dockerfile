# Multi-stage Dockerfile for CodeBench with Python and Java support
FROM openjdk:17-jdk-slim as java-base

# Install Python and pip
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*

# Create a virtual environment
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Set environment variables
ENV PORT=9001
ENV FLASK_ENV=production
ENV PYTHONPATH=/app

# Expose port
EXPOSE 9001

# Run the application
CMD ["python", "codebench.py"]

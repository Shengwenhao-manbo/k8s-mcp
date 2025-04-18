# Use an official Python image as the base image
FROM python:3.13-slim AS base

# Set the working directory
WORKDIR /app

# Install uv and other necessary tools
RUN pip install --no-cache-dir uv

# Install kubectl
RUN apt-get update && \
    apt-get install -y curl && \
    curl -LO https://storage.googleapis.com/kubernetes-release/release/$(curl -s https://storage.googleapis.com/kubernetes-release/release/stable.txt)/bin/linux/amd64/kubectl && \
    chmod +x ./kubectl && \
    mv ./kubectl /usr/local/bin/kubectl

# Copy the necessary files
COPY pyproject.toml uv.lock ./

# Install the project's dependencies
RUN pip install --no-cache-dir poetry && \
    poetry config virtualenvs.create false && \
    poetry check && \
    poetry install --no-interaction --no-ansi --no-root || \
    (echo "Poetry configuration is invalid. Please check pyproject.toml." && exit 1)

# Copy the rest of the application files
COPY . .

# Copy kubeconfig file into container
COPY kubeconfig /root/.kube/config

# Set environment variable for ANTHROPIC_API_KEY
# This can be overridden at runtime
ENV ANTHROPIC_API_KEY=your_api_key_here

# Expose the port that the server will run on
EXPOSE 8081

# Default command to run the server
CMD ["uv", "run", "mcp-k8s.py"]
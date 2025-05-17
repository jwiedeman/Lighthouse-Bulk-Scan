FROM python:3.11-slim

# Install node and lighthouse CLI
RUN apt-get update \
    && apt-get install -y nodejs npm \
    && npm install -g lighthouse \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

ENTRYPOINT ["python", "main.py"]
CMD ["--help"]

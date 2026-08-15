FROM mcr.microsoft.com/playwright/python:v1.62.0-noble

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium

COPY src ./src

RUN mkdir -p /app/data/results

VOLUME ["/app/data"]

EXPOSE 8080

ENTRYPOINT ["python", "-m", "src.main"]

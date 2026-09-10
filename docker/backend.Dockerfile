FROM python:3.12-slim

WORKDIR /app

# libjpeg/zlib for Pillow, qpdf for pikepdf
RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo zlib1g qpdf \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

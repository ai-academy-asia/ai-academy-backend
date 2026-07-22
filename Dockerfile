FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Apply migrations, then serve with gunicorn (gthread for I/O-bound Flask).
CMD ["sh", "-c", "flask db upgrade && exec gunicorn -w 2 --threads 4 --timeout 120 -b 0.0.0.0:8000 wsgi:app"]

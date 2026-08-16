FROM python:3.12-slim

# Stored timestamps stay UTC (see app/timeutil.py); TZ is what the *container*
# reads as now — log lines and anything printed as a wall clock. Left at the
# image default (UTC) those read eight hours behind the office that files on
# them. tzdata ships with the base image, so this is a variable, not a package.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Ulaanbaatar

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Apply migrations, then serve with gunicorn (gthread for I/O-bound Flask).
CMD ["sh", "-c", "flask db upgrade && exec gunicorn -w 2 --threads 4 --timeout 120 -b 0.0.0.0:8000 wsgi:app"]

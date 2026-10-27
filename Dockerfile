FROM python:3.11-slim

# Don't write .pyc files, and don't buffer logs.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# Run as an unprivileged user, not root. If the Firebase key is a Render
# Secret File, it must be readable by this user (or use FIREBASE_CREDENTIALS_JSON).
RUN useradd --system --uid 10001 --no-create-home appuser
USER appuser

EXPOSE 8080
# --proxy-headers: take the client address from Render's proxy headers.
# --no-server-header: don't advertise the server software.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*", "--no-server-header"]

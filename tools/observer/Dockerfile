FROM python:3.12.13-alpine
WORKDIR /app
COPY observer.py /app/observer.py
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 9108
HEALTHCHECK --interval=10s --timeout=3s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:9108/health',timeout=2)"
CMD ["python", "/app/observer.py"]

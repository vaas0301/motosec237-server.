# MOTOSEC 237 v0.1 — image du serveur EN LIGNE.
# Construction : docker build -t motosec237-server:0.1.0 .
# Lancement : docker run -p 8000:8000 --env-file .env motosec237-server:0.1.0
# Ne JAMAIS mettre de secret dans l'image : ils arrivent par variables
# d'environnement au lancement (voir .env.example).
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py geo.py pricing.py otp.py ./
COPY ../db/schema.sql ../db/schema.sql
ENV DATABASE_URL=sqlite:///./motosec237.db
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

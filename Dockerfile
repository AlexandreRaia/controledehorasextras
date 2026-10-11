FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Sem privilegio de root dentro do container.
RUN useradd --create-home app
USER app

EXPOSE 5000

# Configuracao (DATABASE_URL, SECRET_KEY...) vem das variaveis de ambiente
# do EasyPanel; o .env nao entra na imagem.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "4", \
     "--timeout", "60", "--access-logfile", "-", "run:app"]

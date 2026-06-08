FROM python:3.11-slim

WORKDIR /app

# Instalar dependencias
COPY docker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código de la API
COPY docker/ /app/docker/

# Exponer puerto
EXPOSE 8000

# Ejecutar la API desde la carpeta docker
CMD ["uvicorn", "docker.brain_api:app", "--host", "0.0.0.0", "--port", "8000"]

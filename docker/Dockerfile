FROM python:3.11-slim

WORKDIR /app

# Instalar dependencias del sistema (necesarias para numpy/pandas)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copiar e instalar dependencias Python
COPY docker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Verificar versión de scikit-learn instalada
RUN python -c "import sklearn; print(f'✅ scikit-learn {sklearn.__version__} instalado')"

# Copiar el código de la API
COPY docker/ /app/docker/

# Crear directorio de modelos (se montará como volumen)
RUN mkdir -p /app/models

# Exponer puerto
EXPOSE 8000

# Health check: verifica que la API responda
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/')" || exit 1

# Ejecutar la API desde la carpeta docker
CMD ["uvicorn", "docker.brain_api:app", "--host", "0.0.0.0", "--port", "8000"]

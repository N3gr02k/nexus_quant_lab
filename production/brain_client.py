"""
[EXP-021] BrainDockerClient — Puente Windows → Docker
======================================================
El orquestador Windows (MT5) usa este cliente para hablar con el
Cerebro en Docker vía REST API (FastAPI).

Resiliencia:
  - Timeout de 3s para no bloquear el loop de trading
  - Fail-safe: si Docker está offline, activa Veto Automático
  - Contador de fallos para diagnóstico

Protocolo:
  POST /evaluate  →  {features_dict}  →  {state, veto, reason, details}
  GET  /          →  Health Check
"""

import requests
import time
import logging

logger = logging.getLogger(__name__)


class BrainDockerClient:
    """
    Cliente REST para el cerebro en contenedor Docker.
    Reemplaza la inferencia local (scaler + XGBoost) por una llamada HTTP.
    """

    def __init__(self, url="http://localhost:8000/evaluate"):
        self.url = url
        self.fail_count = 0
        self.last_success = 0.0

    def evaluate(self, features_dict: dict) -> tuple:
        """
        Envía los 15 factores alfa a Docker y recibe el veredicto.

        Args:
            features_dict: Diccionario con los 15 factores alfa
                          (generado por get_alpha_vector_15d)

        Returns:
            tuple: (state, veto, reason, details)
                   - state: str o None si falla
                   - veto: bool (True = no operar)
                   - reason: str explicativa
                   - details: dict con info adicional
        """
        try:
            response = requests.post(self.url, json=features_dict, timeout=3)

            if response.status_code == 200:
                data = response.json()
                self.fail_count = 0
                self.last_success = time.time()
                return data['state'], data['veto'], data['reason'], data['details']
            else:
                logger.warning(f"⚠️ Docker respondió con status {response.status_code}")
                return None, True, f"Error API: {response.status_code}", {}

        except requests.exceptions.Timeout:
            self.fail_count += 1
            logger.error(f"⏱️ Timeout al contactar Docker (intento {self.fail_count})")
            return None, True, "Cerebro Docker: Timeout (3s)", {}

        except requests.exceptions.ConnectionError as e:
            self.fail_count += 1
            logger.error(f"🔌 Docker no disponible: {e}")
            return None, True, f"Cerebro Docker Offline ({self.fail_count} fallos)", {}

        except Exception as e:
            self.fail_count += 1
            logger.error(f"❌ Error inesperado en BrainDockerClient: {e}")
            return None, True, f"Error de comunicación: {e}", {}

    def check_health(self) -> dict:
        """
        Verifica que el cerebro Docker esté vivo.

        Returns:
            dict con status del servidor o None si no responde
        """
        try:
            r = requests.get("http://localhost:8000/", timeout=2)
            if r.status_code == 200:
                return r.json()
            return None
        except Exception:
            return None

    def is_online(self) -> bool:
        """Devuelve True si el cerebro Docker respondió exitosamente."""
        health = self.check_health()
        return health is not None and health.get('status') == 'online'

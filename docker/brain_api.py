"""
NEXUS QUANT LAB — Brain API (Puente FastAPI)
=============================================
Este microservicio expone el motor SentinelV2 como una API REST.
El Ejecutor (Host Windows) envía los 15 factores alfa y recibe
la decisión del Cerebro (contenedor Docker).

Endpoints:
    POST /evaluate  →  Evalúa el estado del mercado con los 15 factores
    GET  /          →  Health check para el orquestador
"""

from fastapi import FastAPI, HTTPException
from sentinel_v2_engine import SentinelV2Engine
import logging

# ─── Configuración de logging ───
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("BrainAPI")

# ─── Instancia global del motor (se carga una vez al arrancar) ───
app = FastAPI(
    title="Nexus Quant Lab — Brain API",
    description="Cerebro Cuántico: Evaluación de mercado con SentinelV2",
    version="8.4.2",
)

engine = SentinelV2Engine()
logger.info("🧠 Brain API iniciada. SentinelV2 listo para recibir consultas.")


@app.get("/")
def health_check():
    """Health check: devuelve el estado del Cerebro y las features esperadas."""
    models_loaded = engine.scaler is not None
    return {
        "status": "online",
        "version": "8.4.2",
        "features_expected": 15,
        "models_loaded": models_loaded,
    }


@app.post("/evaluate")
def evaluate_market(features: dict):
    """
    Recibe los 15 factores de Windows y devuelve el Veredicto.

    Ejemplo de features:
    {
        "spread": 0.00012,
        "volume": 1500,
        "rsi_14": 45.2,
        "ma_ratio_50_200": 1.002,
        ... (15 factores en total)
    }
    """
    try:
        state, veto, reason, details = engine.evaluate(features)
        # ─── [EXP-021] SELLO DE ORIGEN: Prueba de trazabilidad ───
        # Este campo demuestra que la inferencia ocurre dentro del contenedor Docker,
        # no en el host Windows. Se usa para validación del Quantum Bridge.
        details['processed_by'] = "DOCKER_LINUAX_CONTAINER"
        # ─────────────────────────────────────────────────────────
        return {
            "state": state,
            "veto": veto,
            "reason": reason,
            "details": details,
        }
    except Exception as e:
        logger.error(f"Error evaluando mercado: {e}")
        raise HTTPException(status_code=500, detail=str(e))

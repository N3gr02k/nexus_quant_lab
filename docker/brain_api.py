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

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError
from docker.sentinel_v2_engine import SentinelV2Engine
import logging
import sys
import sklearn

# ─── Configuración de logging ───
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("BrainAPI")

# ─── Modelo Pydantic para validación de features (EXP-009) ───
class MarketFeatures(BaseModel):
    """Los 15 factores alfa que el cerebro necesita para evaluar el mercado."""
    alpha_divergence: float = Field(..., description="Divergencia de precio/volumen")
    alpha_rejection_z: float = Field(..., description="Z-score de rechazo en EURUSD")
    alpha_rejection_z_gold: float = Field(..., description="Z-score de rechazo en XAUUSD")
    alpha_micro_trend: float = Field(..., description="Micro-tendencia EURUSD")
    alpha_micro_trend_gold: float = Field(..., description="Micro-tendencia XAUUSD")
    alpha_near_high: float = Field(..., description="Cercanía a máximo reciente")
    alpha_near_low: float = Field(..., description="Cercanía a mínimo reciente")
    alpha_is_fixing_hour: float = Field(..., description="Hora de fixing (1.0 o 0.0)")
    alpha_is_ny_session: float = Field(..., description="Sesión NY (1.0 o 0.0)")
    alpha_mom_3h: float = Field(..., description="Momentum 3 horas")
    alpha_mom_6h: float = Field(..., description="Momentum 6 horas")
    alpha_mom_12h: float = Field(..., description="Momentum 12 horas")
    alpha_regime_high_vol: float = Field(..., description="Régimen de alta volatilidad")
    alpha_regime_low_vol: float = Field(..., description="Régimen de baja volatilidad")
    alpha_regime_normal: float = Field(..., description="Régimen normal")


# ─── Instancia global del motor (se carga una vez al arrancar) ───
app = FastAPI(
    title="Nexus Quant Lab — Brain API",
    description="Cerebro Cuántico: Evaluación de mercado con SentinelV2",
    version="8.4.2",
)

engine = SentinelV2Engine()
logger.info("🧠 Brain API iniciada. SentinelV2 listo para recibir consultas.")


# ─── Manejador global para errores de validación Pydantic ───
@app.exception_handler(ValidationError)
async def validation_exception_handler(request: Request, exc: ValidationError):
    """Devuelve un mensaje claro cuando falla la validación de features."""
    errors = exc.errors()
    logger.warning(f"❌ Validación fallida: {errors}")
    return JSONResponse(
        status_code=422,
        content={
            "error": "Datos de entrada inválidos",
            "detail": errors,
            "hint": "Asegúrate de enviar los 15 factores alfa como números (float/int)",
            "expected_fields": list(MarketFeatures.model_fields.keys()),
        },
    )


@app.get("/")
def health_check():
    """Health check: devuelve el estado del Cerebro y las features esperadas."""
    models_loaded = engine.scaler is not None
    sklearn_version = sklearn.__version__
    return {
        "status": "online",
        "version": "8.4.2",
        "features_expected": 15,
        "models_loaded": models_loaded,
        "sklearn_version": sklearn_version,
        "python_version": sys.version.split()[0],
    }


@app.get("/diagnose")
def diagnose():
    """
    Endpoint de diagnóstico: verifica que los modelos .pkl sean compatibles
    con la versión actual de scikit-learn.
    """
    sklearn_version = sklearn.__version__
    result = {
        "sklearn_version": sklearn_version,
        "models_loaded": engine.scaler is not None,
        "models_dir": engine.models_dir,
    }
    
    if engine.scaler is not None:
        # Verificar versión de sklearn con la que se entrenó el scaler
        result["scaler_type"] = type(engine.scaler).__module__
        result["pca_type"] = type(engine.pca).__module__
        result["model_type"] = type(engine.model).__module__
        result["status"] = "✅ Todos los modelos cargados correctamente"
    else:
        result["status"] = "❌ Modelos no cargados - revisa la carpeta models/"
    
    return result


@app.post("/evaluate")
def evaluate_market(features: MarketFeatures):
    """
    Recibe los 15 factores de Windows y devuelve el Veredicto.

    Ejemplo de features:
    {
        "alpha_divergence": 0.5,
        "alpha_rejection_z": -1.2,
        "alpha_rejection_z_gold": 0.8,
        ... (15 factores en total)
    }
    """
    try:
        # Convertir el modelo Pydantic a dict para el motor
        features_dict = features.model_dump()
        state, veto, reason, details = engine.evaluate(features_dict)
        # ─── [EXP-021] SELLO DE ORIGEN: Prueba de trazabilidad ───
        # Este campo demuestra que la inferencia ocurre dentro del contenedor Docker,
        # no en el host Windows. Se usa para validación del Quantum Bridge.
        details['processed_by'] = "DOCKER_LINUX_CONTAINER"
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



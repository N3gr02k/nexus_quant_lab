"""
NEXUS QUANT LAB — TEST V10.4: Integración Meta-Brain
=====================================================
test_v104.py

Prueba los nuevos métodos de integración:
  - update_system_state()
  - save_state() / load_state()
  - evaluate_signal() (wrapper simplificado)
  - Parámetros directos en __init__

Autor: Nexus Quant Lab
Fecha: 2026-06-09
"""

import sys
import os
import logging
import json
import tempfile

# Asegurar que podemos importar core
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.meta_brain_v10 import MetaBrainV10, MarketState, SystemAlert

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("TestV104")


def test_01_init_with_direct_params():
    """Test: Inicializar con parámetros directos."""
    logger.info("=" * 60)
    logger.info("TEST 01: Init con parámetros directos")
    logger.info("=" * 60)

    brain = MetaBrainV10(
        confidence_threshold=0.65,
        risk_per_trade=0.015,
        sl_atr=2.0,
        tp_atr=3.0,
    )

    assert brain.config["default_confidence_threshold"] == 0.65, \
        f"Expected 0.65, got {brain.config['default_confidence_threshold']}"
    assert brain.config["default_risk_per_trade"] == 0.015, \
        f"Expected 0.015, got {brain.config['default_risk_per_trade']}"
    assert brain.config["default_sl_atr"] == 2.0, \
        f"Expected 2.0, got {brain.config['default_sl_atr']}"
    assert brain.config["default_tp_atr"] == 3.0, \
        f"Expected 3.0, got {brain.config['default_tp_atr']}"

    logger.info("✅ TEST 01 PASSED: Parámetros directos aplicados correctamente")
    return brain


def test_02_update_system_state():
    """Test: update_system_state actualiza caché."""
    logger.info("=" * 60)
    logger.info("TEST 02: update_system_state")
    logger.info("=" * 60)

    brain = MetaBrainV10()

    # Valores iniciales (deben ser defaults)
    assert getattr(brain, "_cached_win_rate", 0.5) == 0.5
    assert getattr(brain, "_cached_drawdown", 0.0) == 0.0

    # Actualizar
    brain.update_system_state(
        win_rate_24h=0.45,
        drawdown=0.08,
        consecutive_losses=3,
        latency_ms=250,
        brain_confidence=0.60,
    )

    assert brain._cached_win_rate == 0.45
    assert brain._cached_drawdown == 0.08
    assert brain._cached_consecutive_losses == 3
    assert brain._cached_latency == 250
    assert brain._cached_brain_confidence == 0.60

    logger.info("✅ TEST 02 PASSED: System state actualizado correctamente")


def test_03_evaluate_signal_wrapper():
    """Test: evaluate_signal usa valores cacheados."""
    logger.info("=" * 60)
    logger.info("TEST 03: evaluate_signal wrapper")
    logger.info("=" * 60)

    brain = MetaBrainV10()

    # Primero actualizar estado del sistema
    brain.update_system_state(
        win_rate_24h=0.55,
        drawdown=0.03,
        consecutive_losses=1,
        latency_ms=100,
        brain_confidence=0.70,
    )

    # Usar wrapper simplificado
    decision = brain.evaluate_signal(
        probability=0.72,
        expected_reward_ratio=2.5,
        atr_current=0.0012,
        atr_median=0.0010,
        volume_delta=0.65,
        momentum_3h=0.45,
        momentum_6h=0.55,
        divergence=0.0005,
        hour_utc=14,
    )

    assert decision is not None
    assert hasattr(decision, "should_trade")
    assert hasattr(decision, "utility_score")
    assert hasattr(decision, "adjusted_risk_pct")

    logger.info(f"   Decisión: {'TRADE' if decision.should_trade else 'NO TRADE'}")
    logger.info(f"   Utility: {decision.utility_score:.4f}")
    logger.info(f"   Riesgo: {decision.adjusted_risk_pct*100:.2f}%")
    logger.info("✅ TEST 03 PASSED: evaluate_signal wrapper funciona")


def test_04_save_and_load_state():
    """Test: Guardar y cargar estado del Meta-Brain."""
    logger.info("=" * 60)
    logger.info("TEST 04: save_state / load_state")
    logger.info("=" * 60)

    # Crear brain y hacer una evaluación
    brain = MetaBrainV10()
    brain.evaluate(
        probability=0.72,
        expected_reward_ratio=2.5,
        atr_current=0.0012,
        atr_median=0.0010,
        volume_delta=0.65,
        momentum_3h=0.45,
        momentum_6h=0.55,
        divergence=0.0005,
        hour_utc=14,
        win_rate_24h=0.62,
        drawdown=0.02,
        consecutive_losses=0,
        latency_ms=45,
        brain_confidence=0.78,
    )

    # Guardar en archivo temporal
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        temp_path = f.name

    try:
        saved_path = brain.save_state(temp_path)
        assert os.path.exists(saved_path), f"File not found: {saved_path}"

        # Verificar contenido
        with open(saved_path, "r") as f:
            data = json.load(f)

        assert "version" in data
        assert data["version"] == "V10.3"
        assert "config" in data
        assert "state" in data
        assert "calibration" in data
        assert "last_market_diagnosis" in data
        assert "last_system_diagnosis" in data
        assert "last_utility_decision" in data

        logger.info(f"   Archivo guardado: {saved_path}")
        logger.info(f"   Versión: {data['version']}")
        logger.info(f"   Market state: {data['last_market_diagnosis']['market_state']}")
        logger.info(f"   System alert: {data['last_system_diagnosis']['system_alert']}")
        logger.info(f"   Utility: {data['last_utility_decision']['utility_score']}")

        # Crear nuevo brain y cargar estado
        brain2 = MetaBrainV10()
        loaded = brain2.load_state(temp_path)
        assert loaded, "load_state returned False"

        # Verificar que se restauró la configuración
        assert brain2.config["default_confidence_threshold"] == brain.config["default_confidence_threshold"]
        assert brain2.config["default_risk_per_trade"] == brain.config["default_risk_per_trade"]

        # Verificar que se restauró el estado
        assert brain2.state["total_evaluations"] == brain.state["total_evaluations"]

        logger.info("✅ TEST 04 PASSED: save_state / load_state funcionan")

    finally:
        # Limpiar
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def test_05_load_state_nonexistent():
    """Test: load_state con archivo inexistente."""
    logger.info("=" * 60)
    logger.info("TEST 05: load_state con archivo inexistente")
    logger.info("=" * 60)

    brain = MetaBrainV10()
    result = brain.load_state("/nonexistent/path/state.json")
    assert not result, "load_state should return False for nonexistent file"

    logger.info("✅ TEST 05 PASSED: load_state maneja archivos inexistentes")


def test_06_evaluate_signal_without_update():
    """Test: evaluate_signal sin update_system_state previo."""
    logger.info("=" * 60)
    logger.info("TEST 06: evaluate_signal sin update previo")
    logger.info("=" * 60)

    brain = MetaBrainV10()

    # Sin llamar a update_system_state, debe usar defaults
    decision = brain.evaluate_signal(
        probability=0.65,
        expected_reward_ratio=2.0,
        atr_current=0.0015,
        atr_median=0.0012,
        volume_delta=0.45,
        momentum_3h=0.35,
        momentum_6h=0.40,
        divergence=0.0008,
        hour_utc=10,
    )

    assert decision is not None
    logger.info(f"   Decisión: {'TRADE' if decision.should_trade else 'NO TRADE'}")
    logger.info(f"   Utility: {decision.utility_score:.4f}")
    logger.info("✅ TEST 06 PASSED: evaluate_signal funciona sin update previo")


def test_07_generate_dynamic_config():
    """Test: generate_dynamic_config produce salida correcta."""
    logger.info("=" * 60)
    logger.info("TEST 07: generate_dynamic_config")
    logger.info("=" * 60)

    brain = MetaBrainV10()

    # Sin evaluación previa
    config = brain.generate_dynamic_config()
    assert "meta_brain_version" in config
    assert config["meta_brain_version"] == "V10.3"
    assert "params" in config
    assert "limits" in config
    assert "hibernation" in config
    assert config["hibernation"] == False
    assert config["should_trade"] == False  # Sin evaluación

    # Hacer una evaluación
    brain.evaluate(
        probability=0.72,
        expected_reward_ratio=2.5,
        atr_current=0.0012,
        atr_median=0.0010,
        volume_delta=0.65,
        momentum_3h=0.45,
        momentum_6h=0.55,
        divergence=0.0005,
        hour_utc=14,
        win_rate_24h=0.62,
        drawdown=0.02,
        consecutive_losses=0,
        latency_ms=45,
        brain_confidence=0.78,
    )

    config2 = brain.generate_dynamic_config()
    assert config2["market_state"] == "GOLDEN_STATE"
    assert config2["system_alert"] == "NORMAL"
    assert config2["utility_score"] > 0
    assert "params" in config2
    assert config2["params"]["risk_per_trade"] > 0
    assert config2["params"]["sl_atr"] > 0
    assert config2["params"]["tp_atr"] > 0

    logger.info(f"   Market state: {config2['market_state']}")
    logger.info(f"   System alert: {config2['system_alert']}")
    logger.info(f"   Utility: {config2['utility_score']}")
    logger.info(f"   Should trade: {config2['should_trade']}")
    logger.info(f"   Risk: {config2['params']['risk_per_trade']*100:.2f}%")
    logger.info("✅ TEST 07 PASSED: generate_dynamic_config produce salida correcta")


def test_08_full_integration_flow():
    """Test: Flujo completo de integración."""
    logger.info("=" * 60)
    logger.info("TEST 08: Flujo completo de integración")
    logger.info("=" * 60)

    # 1. Inicializar con parámetros personalizados
    brain = MetaBrainV10(
        confidence_threshold=0.60,
        risk_per_trade=0.012,
        sl_atr=1.8,
        tp_atr=2.5,
    )

    # 2. Actualizar estado del sistema
    brain.update_system_state(
        win_rate_24h=0.58,
        drawdown=0.04,
        consecutive_losses=2,
        latency_ms=85,
        brain_confidence=0.72,
    )

    # 3. Evaluar señal con wrapper
    decision = brain.evaluate_signal(
        probability=0.68,
        expected_reward_ratio=2.2,
        atr_current=0.0014,
        atr_median=0.0011,
        volume_delta=0.55,
        momentum_3h=0.38,
        momentum_6h=0.42,
        divergence=0.0007,
        hour_utc=15,
    )

    # 4. Verificar decisión
    assert decision is not None
    logger.info(f"   Decisión: {'TRADE' if decision.should_trade else 'NO TRADE'}")
    logger.info(f"   Utility: {decision.utility_score:.4f}")
    logger.info(f"   Confianza (visual): {decision.adjusted_confidence:.2f}")
    logger.info(f"   Riesgo: {decision.adjusted_risk_pct*100:.2f}%")
    logger.info(f"   SL: {decision.adjusted_sl_atr:.1f} ATR")
    logger.info(f"   TP: {decision.adjusted_tp_atr:.1f} ATR")

    # 5. Generar config dinámica
    config = brain.generate_dynamic_config()
    assert config["params"]["risk_per_trade"] > 0
    logger.info(f"   Config dinámica generada: risk={config['params']['risk_per_trade']*100:.2f}%")

    # 6. Guardar estado
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        temp_path = f.name
    try:
        brain.save_state(temp_path)
        logger.info(f"   Estado guardado en: {temp_path}")

        # 7. Cargar en nuevo brain
        brain2 = MetaBrainV10()
        brain2.load_state(temp_path)
        assert brain2.state["total_evaluations"] == brain.state["total_evaluations"]
        logger.info(f"   Estado cargado: {brain2.state['total_evaluations']} evaluaciones")
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)

    logger.info("✅ TEST 08 PASSED: Flujo completo de integración funciona")


if __name__ == "__main__":
    logger.info("\n" + "=" * 70)
    logger.info("🧠 META-BRAIN V10.4 — TEST DE INTEGRACIÓN")
    logger.info("=" * 70)

    tests = [
        test_01_init_with_direct_params,
        test_02_update_system_state,
        test_03_evaluate_signal_wrapper,
        test_04_save_and_load_state,
        test_05_load_state_nonexistent,
        test_06_evaluate_signal_without_update,
        test_07_generate_dynamic_config,
        test_08_full_integration_flow,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            logger.error(f"❌ {test.__name__} FAILED: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    logger.info("\n" + "=" * 70)
    logger.info(f"📊 RESULTADOS: {passed}/{len(tests)} tests passed")
    if failed > 0:
        logger.error(f"❌ {failed} tests FAILED")
    else:
        logger.info("🎉 TODOS LOS TESTS PASARON")
    logger.info("=" * 70)

"""
NEXUS QUANT LAB — FASE 10: META-BRAIN V10
==========================================
meta_brain_v10.py

TRANSICIÓN: V1 (Reglas) → V2 (Probabilidades) → V3 (Adaptativo Contextual)

ARQUITECTURA DE TRES CAPAS + HIBERNATION:

Capa 1 — Estado del Mercado (market_state)
  Diagnostica el entorno en vivo:
    - volatility_regime: LOW / NORMAL / HIGH / EXTREME
    - liquidity_regime: THIN / NORMAL / DEEP / FLOOD
    - trend_strength: WEAK / MODERATE / STRONG / EXTREME
    - cross_asset_alignment: ALIGNED / NEUTRAL / DIVERGENT
    - session: ASIA / LONDON / NY / FIXING / CLOSED

  Resultado: TOXICO | NORMAL | FAVORABLE | GOLDEN_STATE

Capa 2 — Estado del Sistema (system_state)
  Diagnostica la salud del propio bot:
    - win_rate_24h: ratio de acierto últimas 24h
    - drawdown: drawdown actual desde pico
    - consecutive_losses: racha de pérdidas
    - latency: latencia de inferencia (ms)
    - brain_confidence: confianza media del cerebro

  Resultado: NORMAL | CAUTION | STRESS | CRITICAL | HIBERNATION

Capa 3 — Motor de Utilidad (Utility Engine)
  Fórmula maestra:
    utility = (probability * expected_reward * market_quality) / risk

  donde risk = 1 / (1 + risk_multiplier * 10)

  Decisión:
    if utility > threshold: TRADE
    else: NO TRADE

  La confianza es SOLO para visualización/logging.
  La utility es la métrica maestra de decisión.

ESTADO HIBERNATION:
  Si drawdown > 15% O racha >= 6 O latencia > 1000ms:
    - utility = 0
    - risk = 0
    - No se evalúan señales
    - Solo observación

LÍMITES (Anti-overfitting):
  El Meta-Brain NO puede modificar parámetros libremente.
  Solo puede moverse dentro de rangos predefinidos:
    - confidence_threshold: 0.45 → 0.75 (solo visual)
    - risk_per_trade: 0.25% → 2.5%
    - SL: 1.0 ATR → 3.0 ATR
    - TP: 0.8 ATR → 4.0 ATR

Integración:
  from core.meta_brain_v10 import MetaBrainV10
  brain = MetaBrainV10()
  decision = brain.evaluate(signal, market_data, system_metrics)

Autor: Nexus Quant Lab
Fecha: 2026-06-09 (Fase 10 — Meta-Brain Homeostático)
"""

import numpy as np
import logging
import json
import os
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Optional, Tuple, List, Dict
from enum import Enum

# ──────────────────────────────────────────────
# Configuración
# ──────────────────────────────────────────────
logger = logging.getLogger("MetaBrainV10")


# ══════════════════════════════════════════════
# ENUMS Y TIPOS
# ══════════════════════════════════════════════

class MarketState(Enum):
    """Estados del mercado — Capa 1"""
    TOXICO = "TOXICO"
    NORMAL = "NORMAL"
    FAVORABLE = "FAVORABLE"
    GOLDEN_STATE = "GOLDEN_STATE"


class SystemAlert(Enum):
    """Alertas del sistema — Capa 2"""
    NORMAL = "NORMAL"
    CAUTION = "CAUTION"
    STRESS = "STRESS"
    CRITICAL = "CRITICAL"
    HIBERNATION = "HIBERNATION"


# ══════════════════════════════════════════════
# DATACLASSES DE ENTRADA/SALIDA
# ══════════════════════════════════════════════

@dataclass
class MarketDiagnosis:
    """Diagnóstico completo de la Capa 1 — Estado del Mercado"""
    volatility_regime: str          # LOW / NORMAL / HIGH / EXTREME
    liquidity_regime: str           # THIN / NORMAL / DEEP / FLOOD
    trend_strength: str             # WEAK / MODERATE / STRONG / EXTREME
    cross_asset_alignment: str      # ALIGNED / NEUTRAL / DIVERGENT
    session: str                    # ASIA / LONDON / NY / FIXING / CLOSED
    market_state: MarketState       # TOXICO / NORMAL / FAVORABLE / GOLDEN_STATE
    market_quality: float           # 0.0 → 1.0 (score numérico)
    details: Dict = field(default_factory=dict)


@dataclass
class SystemDiagnosis:
    """Diagnóstico completo de la Capa 2 — Estado del Sistema"""
    win_rate_24h: float             # 0.0 → 1.0
    drawdown: float                 # 0.0 → 1.0 (ej: 0.08 = 8%)
    consecutive_losses: int         # racha actual
    latency_ms: float               # latencia de inferencia
    brain_confidence: float         # confianza media del cerebro 0.0 → 1.0
    system_alert: SystemAlert       # NORMAL / CAUTION / STRESS / CRITICAL / HIBERNATION
    risk_multiplier: float          # 0.0 → 1.0 (factor de reducción de riesgo)
    details: Dict = field(default_factory=dict)


@dataclass
class UtilityDecision:
    """Decisión final del Motor de Utilidad — Capa 3"""
    utility_score: float            # Score de utilidad (métrica maestra)
    threshold: float                # Umbral dinámico
    should_trade: bool              # True si utility > threshold
    adjusted_confidence: float      # Confianza ajustada — SOLO VISUAL (0.45 → 0.75)
    adjusted_risk_pct: float        # Riesgo ajustado (0.25% → 2.5%)
    adjusted_sl_atr: float          # SL ajustado (1.0 → 3.0 ATR)
    adjusted_tp_atr: float          # TP ajustado (0.8 → 4.0 ATR)
    reason: str                     # Razón de la decisión
    details: Dict = field(default_factory=dict)


# ══════════════════════════════════════════════
# META-BRAIN V10 — TRES CAPAS + HIBERNATION
# ══════════════════════════════════════════════

class MetaBrainV10:
    """
    Meta-Brain V10 — Sistema Adaptativo Contextual de Tres Capas.

    Capa 1: Diagnostica el mercado (volatilidad, liquidez, tendencia, etc.)
    Capa 2: Diagnostica el sistema (win rate, drawdown, latencia, etc.)
    Capa 3: Motor de Utilidad que combina todo en una decisión.

    La UTILITY es la métrica maestra. La confianza es SOLO visual.

    HIBERNATION: Modo supervivencia cuando el sistema está crítico.
      - utility = 0, risk = 0, no se evalúan señales.

    Límites (Anti-overfitting):
      - confidence_threshold: 0.45 → 0.75 (solo visual)
      - risk_per_trade: 0.25% → 2.5%
      - SL: 1.0 ATR → 3.0 ATR
      - TP: 0.8 ATR → 4.0 ATR
    """

    # ─── LÍMITES RÍGIDOS (Anti-overfitting) ───
    LIMITS = {
        "confidence_threshold": {"min": 0.45, "max": 0.75},
        "risk_per_trade": {"min": 0.0025, "max": 0.025},  # 0.25% → 2.5%
        "sl_atr": {"min": 1.0, "max": 3.0},
        "tp_atr": {"min": 0.8, "max": 4.0},
    }

    # ─── SESIONES DE MERCADO ───
    SESSIONS = {
        "ASIA": (0, 8),
        "LONDON": (8, 16),
        "NY": (12, 20),
        "FIXING": (18, 20),
    }

    def __init__(
        self,
        config: Optional[dict] = None,
        confidence_threshold: Optional[float] = None,
        risk_per_trade: Optional[float] = None,
        sl_atr: Optional[float] = None,
        tp_atr: Optional[float] = None,
    ):
        """
        Inicializa el Meta-Brain V10.

        Args:
            config: Configuración personalizada (opcional, dict)
            confidence_threshold: Umbral de confianza inicial (0.45-0.75)
            risk_per_trade: Riesgo por trade inicial (0.0025-0.025)
            sl_atr: SL en ATR inicial (1.0-3.0)
            tp_atr: TP en ATR inicial (0.8-4.0)
        """
        # ─── Configuración por defecto ───
        self.config = {
            # Capa 1 — Thresholds de mercado
            "volatility_high_threshold": 1.5,
            "volatility_extreme_threshold": 2.5,
            "liquidity_thin_threshold": 0.3,
            "liquidity_flood_threshold": 0.8,
            "trend_strong_threshold": 0.6,
            "trend_extreme_threshold": 1.2,
            "divergence_threshold": 0.002,

            # Capa 2 — Thresholds del sistema
            "win_rate_low_threshold": 0.40,
            "win_rate_critical_threshold": 0.30,
            "drawdown_caution_threshold": 0.05,
            "drawdown_stress_threshold": 0.10,
            "drawdown_critical_threshold": 0.15,
            "max_consecutive_losses": 3,
            "latency_critical_ms": 500,

            # HIBERNATION — Umbrales de modo supervivencia
            "hibernation_drawdown": 0.15,        # 15% drawdown → HIBERNATION
            "hibernation_consecutive_losses": 6,  # 6 pérdidas seguidas → HIBERNATION
            "hibernation_latency_ms": 1000,       # 1000ms latencia → HIBERNATION

            # Capa 3 — Motor de Utilidad
            "base_utility_threshold": 0.5,
            "min_utility_threshold": 0.3,
            "max_utility_threshold": 0.8,

            # Parámetros por defecto (dentro de límites)
            "default_confidence_threshold": 0.55,
            "default_risk_per_trade": 0.01,         # 1%
            "default_sl_atr": 1.5,
            "default_tp_atr": 2.0,
        }

        # Sobrescribir con configuración personalizada
        if config:
            self._validate_config(config)
            self.config.update(config)

        # ─── Sobrescribir con parámetros directos ───
        if confidence_threshold is not None:
            self.config["default_confidence_threshold"] = confidence_threshold
        if risk_per_trade is not None:
            self.config["default_risk_per_trade"] = risk_per_trade
        if sl_atr is not None:
            self.config["default_sl_atr"] = sl_atr
        if tp_atr is not None:
            self.config["default_tp_atr"] = tp_atr

        # ─── Estado interno del Meta-Brain ───
        self.state = {
            "total_evaluations": 0,
            "total_trades_approved": 0,
            "total_trades_rejected": 0,
            "total_hibernation_events": 0,
            "last_market_diagnosis": None,
            "last_system_diagnosis": None,
            "last_utility_decision": None,
            "history": [],
            # Métricas de rendimiento del Meta-Brain
            "meta_win_rate": 0.5,
            "meta_trades": 0,
            "meta_wins": 0,
        }

        # ─── Historial de trades para calcular win rate dinámico ───
        self._trade_history: List[Dict] = []

        # ─── FASE 10.2: Memoria Operativa ───
        self._feedback_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data", "meta_brain_feedback.json"
        )
        self._feedback: List[Dict] = []
        self._load_feedback()

        # ─── FASE 10.2: Calibración por estado de mercado ───
        # market_state → { trades, wins, wr, market_quality_adj, threshold_adj, risk_adj }
        self._calibration: Dict[str, Dict] = {
            "GOLDEN_STATE": {"trades": 0, "wins": 0, "wr": 0.5, "mq_adj": 1.0, "th_adj": 0.0, "rk_adj": 1.0},
            "FAVORABLE":    {"trades": 0, "wins": 0, "wr": 0.5, "mq_adj": 1.0, "th_adj": 0.0, "rk_adj": 1.0},
            "NORMAL":       {"trades": 0, "wins": 0, "wr": 0.5, "mq_adj": 1.0, "th_adj": 0.0, "rk_adj": 1.0},
            "TOXICO":       {"trades": 0, "wins": 0, "wr": 0.5, "mq_adj": 1.0, "th_adj": 0.0, "rk_adj": 1.0},
        }

        logger.info("=" * 70)
        logger.info("🧠 META-BRAIN V10.3 INICIALIZADO")
        logger.info("   Arquitectura: 3 Capas + HIBERNATION + Memoria Operativa")
        logger.info("   Métrica maestra: UTILITY (confianza es solo visual)")
        logger.info("   Calibración: Ponderada por R-multiple (avg_R + WR)")
        logger.info("   Mínimo trades para recalibrar: 10 (producción: 20)")
        logger.info(f"   Feedback: {self._feedback_path}")
        logger.info(f"   Registros cargados: {len(self._feedback)}")
        logger.info(f"   Límites: confidence=[{self.LIMITS['confidence_threshold']['min']}, "
                    f"{self.LIMITS['confidence_threshold']['max']}], "
                    f"risk=[{self.LIMITS['risk_per_trade']['min']*100:.1f}%, "
                    f"{self.LIMITS['risk_per_trade']['max']*100:.1f}%]")
        logger.info("=" * 70)

    def _validate_config(self, config: dict):
        """Valida que la configuración no exceda los límites."""
        for key, value in config.items():
            if key in self.LIMITS:
                limits = self.LIMITS[key]
                if value < limits["min"] or value > limits["max"]:
                    logger.warning(
                        f"⚠️ {key}={value} fuera de límites [{limits['min']}, {limits['max']}]. "
                        f"Usando valor por defecto."
                    )
                    config[key] = max(limits["min"], min(limits["max"], value))

    # ══════════════════════════════════════════
    # CAPA 1 — ESTADO DEL MERCADO
    # ══════════════════════════════════════════

    def _detect_session(self, hour_utc: int) -> str:
        """Detecta la sesión de mercado actual."""
        if 0 <= hour_utc < 8:
            return "ASIA"
        elif 8 <= hour_utc < 12:
            return "LONDON"
        elif 12 <= hour_utc < 18:
            return "NY"
        elif 18 <= hour_utc < 20:
            return "FIXING"
        else:
            return "CLOSED"

    def _diagnose_market(
        self,
        atr_current: float,
        atr_median: float,
        volume_delta: float,
        momentum_3h: float,
        momentum_6h: float,
        divergence: float,
        hour_utc: int,
        rejection_speed: float,
        tick_vol_std: float,
    ) -> MarketDiagnosis:
        """
        Capa 1: Diagnostica el estado del mercado.

        Args:
            atr_current: ATR actual
            atr_median: ATR mediano histórico
            volume_delta: Volume delta normalizado (-1 a 1)
            momentum_3h: Momentum de 3 horas
            momentum_6h: Momentum de 6 horas
            divergence: Divergencia cross-asset
            hour_utc: Hora UTC actual
            rejection_speed: Velocidad de rechazo
            tick_vol_std: Desviación estándar del volumen de ticks

        Returns:
            MarketDiagnosis con el diagnóstico completo
        """
        # ─── Volatilidad ───
        vol_ratio = atr_current / max(atr_median, 1e-10)
        if vol_ratio >= self.config["volatility_extreme_threshold"]:
            volatility_regime = "EXTREME"
        elif vol_ratio >= self.config["volatility_high_threshold"]:
            volatility_regime = "HIGH"
        elif vol_ratio >= 0.8:
            volatility_regime = "NORMAL"
        else:
            volatility_regime = "LOW"

        # ─── Liquidez ───
        abs_vol_delta = abs(volume_delta)
        if abs_vol_delta >= self.config["liquidity_flood_threshold"]:
            liquidity_regime = "FLOOD"
        elif abs_vol_delta >= 0.5:
            liquidity_regime = "DEEP"
        elif abs_vol_delta >= self.config["liquidity_thin_threshold"]:
            liquidity_regime = "NORMAL"
        else:
            liquidity_regime = "THIN"

        # ─── Fuerza de tendencia ───
        max_mom = max(abs(momentum_3h), abs(momentum_6h))
        if max_mom >= self.config["trend_extreme_threshold"]:
            trend_strength = "EXTREME"
        elif max_mom >= self.config["trend_strong_threshold"]:
            trend_strength = "STRONG"
        elif max_mom >= 0.3:
            trend_strength = "MODERATE"
        else:
            trend_strength = "WEAK"

        # ─── Alineación cross-asset ───
        if abs(divergence) >= self.config["divergence_threshold"]:
            cross_asset_alignment = "DIVERGENT"
        elif abs(divergence) >= self.config["divergence_threshold"] * 0.5:
            cross_asset_alignment = "NEUTRAL"
        else:
            cross_asset_alignment = "ALIGNED"

        # ─── Sesión ───
        session = self._detect_session(hour_utc)

        # ─── Cálculo del Market Quality Score (0.0 → 1.0) ───
        quality_score = 1.0

        # Penalizar volatilidad extrema
        if volatility_regime == "EXTREME":
            quality_score *= 0.3
        elif volatility_regime == "HIGH":
            quality_score *= 0.6

        # Penalizar liquidez thin
        if liquidity_regime == "THIN":
            quality_score *= 0.4
        elif liquidity_regime == "FLOOD":
            quality_score *= 0.7

        # Penalizar divergencia
        if cross_asset_alignment == "DIVERGENT":
            quality_score *= 0.5

        # Bonificar tendencia fuerte y alineada
        if trend_strength in ("STRONG", "EXTREME") and cross_asset_alignment == "ALIGNED":
            quality_score *= 1.5  # V10.1: más agresivo (era 1.2)

        # Penalizar sesión de fixing
        if session == "FIXING":
            quality_score *= 0.5

        # Bonificar sesión NY (mayor liquidez)
        if session == "NY" and liquidity_regime in ("DEEP", "NORMAL"):
            quality_score *= 1.2  # V10.1: más agresivo (era 1.1)

        # Asegurar rango [0, 1]
        quality_score = max(0.0, min(1.0, quality_score))

        # ─── Determinar Market State ───
        if quality_score >= 0.85:
            market_state = MarketState.GOLDEN_STATE
        elif quality_score >= 0.60:
            market_state = MarketState.FAVORABLE
        elif quality_score >= 0.35:
            market_state = MarketState.NORMAL
        else:
            market_state = MarketState.TOXICO

        diagnosis = MarketDiagnosis(
            volatility_regime=volatility_regime,
            liquidity_regime=liquidity_regime,
            trend_strength=trend_strength,
            cross_asset_alignment=cross_asset_alignment,
            session=session,
            market_state=market_state,
            market_quality=quality_score,
            details={
                "vol_ratio": round(vol_ratio, 2),
                "abs_vol_delta": round(abs_vol_delta, 3),
                "max_mom": round(max_mom, 4),
                "divergence": round(divergence, 5),
                "rejection_speed": round(rejection_speed, 2),
                "tick_vol_std": round(tick_vol_std, 2),
            }
        )

        logger.info(
            f"📊 CAPA 1 — MERCADO: {market_state.value} | "
            f"Vol={volatility_regime} | Liq={liquidity_regime} | "
            f"Trend={trend_strength} | Cross={cross_asset_alignment} | "
            f"Sesión={session} | Quality={quality_score:.2f}"
        )

        return diagnosis

    # ══════════════════════════════════════════
    # CAPA 2 — ESTADO DEL SISTEMA + HIBERNATION
    # ══════════════════════════════════════════

    def _diagnose_system(
        self,
        win_rate_24h: float,
        drawdown: float,
        consecutive_losses: int,
        latency_ms: float,
        brain_confidence: float,
    ) -> SystemDiagnosis:
        """
        Capa 2: Diagnostica la salud del sistema.

        Incluye detección de HIBERNATION:
          - drawdown > 15%
          - consecutive_losses >= 6
          - latency > 1000ms

        Args:
            win_rate_24h: Win rate de las últimas 24h (0-1)
            drawdown: Drawdown actual (0-1)
            consecutive_losses: Rachas de pérdidas consecutivas
            latency_ms: Latencia de inferencia en ms
            brain_confidence: Confianza media del cerebro (0-1)

        Returns:
            SystemDiagnosis con el diagnóstico completo
        """
        # ─── Verificar HIBERNATION primero ───
        hibernation_reasons = []
        if drawdown >= self.config["hibernation_drawdown"]:
            hibernation_reasons.append(f"DD={drawdown:.1%}≥{self.config['hibernation_drawdown']:.0%}")
        if consecutive_losses >= self.config["hibernation_consecutive_losses"]:
            hibernation_reasons.append(f"Racha={consecutive_losses}≥{self.config['hibernation_consecutive_losses']}")
        if latency_ms >= self.config["hibernation_latency_ms"]:
            hibernation_reasons.append(f"Lat={latency_ms:.0f}ms≥{self.config['hibernation_latency_ms']:.0f}ms")

        if hibernation_reasons:
            diagnosis = SystemDiagnosis(
                win_rate_24h=win_rate_24h,
                drawdown=drawdown,
                consecutive_losses=consecutive_losses,
                latency_ms=latency_ms,
                brain_confidence=brain_confidence,
                system_alert=SystemAlert.HIBERNATION,
                risk_multiplier=0.0,  # Riesgo CERO en hibernación
                details={
                    "hibernation_reasons": hibernation_reasons,
                    "risk_multiplier": 0.0,
                }
            )
            logger.info(
                f"🖥️ CAPA 2 — SISTEMA: HIBERNATION 🧊 | "
                f"Razones: {', '.join(hibernation_reasons)} | "
                f"RiskMult=0.00"
            )
            return diagnosis

        # ─── Si no hay HIBERNATION, evaluar alerta normal ───
        alert = SystemAlert.NORMAL
        risk_multiplier = 1.0

        # Evaluar drawdown
        if drawdown >= self.config["drawdown_critical_threshold"]:
            alert = SystemAlert.CRITICAL
            risk_multiplier = 0.1
        elif drawdown >= self.config["drawdown_stress_threshold"]:
            alert = SystemAlert.STRESS
            risk_multiplier = 0.3
        elif drawdown >= self.config["drawdown_caution_threshold"]:
            alert = SystemAlert.CAUTION
            risk_multiplier = 0.6

        # Evaluar win rate (puede empeorar la alerta)
        if win_rate_24h < self.config["win_rate_critical_threshold"]:
            alert = SystemAlert.CRITICAL
            risk_multiplier = min(risk_multiplier, 0.15)
        elif win_rate_24h < self.config["win_rate_low_threshold"]:
            if alert.value < SystemAlert.STRESS.value:
                alert = SystemAlert.STRESS
            risk_multiplier = min(risk_multiplier, 0.4)

        # Evaluar pérdidas consecutivas
        if consecutive_losses >= self.config["max_consecutive_losses"]:
            if alert.value < SystemAlert.STRESS.value:
                alert = SystemAlert.STRESS
            risk_multiplier = min(risk_multiplier, 0.3)

        # Evaluar latencia
        if latency_ms >= self.config["latency_critical_ms"]:
            if alert.value < SystemAlert.CRITICAL.value:
                alert = SystemAlert.CRITICAL
            risk_multiplier = min(risk_multiplier, 0.1)

        # Evaluar confianza del cerebro
        if brain_confidence < 0.3:
            risk_multiplier = min(risk_multiplier, 0.5)

        diagnosis = SystemDiagnosis(
            win_rate_24h=win_rate_24h,
            drawdown=drawdown,
            consecutive_losses=consecutive_losses,
            latency_ms=latency_ms,
            brain_confidence=brain_confidence,
            system_alert=alert,
            risk_multiplier=risk_multiplier,
            details={
                "alert_value": alert.value,
                "risk_multiplier": round(risk_multiplier, 3),
            }
        )

        logger.info(
            f"🖥️ CAPA 2 — SISTEMA: {alert.value} | "
            f"WR={win_rate_24h:.1%} | DD={drawdown:.1%} | "
            f"Racha={consecutive_losses} | Lat={latency_ms:.0f}ms | "
            f"Conf={brain_confidence:.2f} | RiskMult={risk_multiplier:.2f}"
        )

        return diagnosis

    # ══════════════════════════════════════════
    # CAPA 3 — MOTOR DE UTILIDAD
    # ══════════════════════════════════════════

    def _calculate_utility(
        self,
        probability: float,
        expected_reward_ratio: float,
        market_quality: float,
        risk_multiplier: float,
        is_hibernation: bool = False,
    ) -> Tuple[float, float]:
        """
        Capa 3: Calcula el Utility Score y el umbral dinámico.

        FÓRMULA MAESTRA:
          utility = (probability * expected_reward * market_quality) / risk

        donde risk = 1 / (1 + risk_multiplier * 10)
          - risk_multiplier = 1.0 → risk = 0.091 → utility se divide por ~0.09 (aumenta)
          - risk_multiplier = 0.1 → risk = 0.5   → utility se divide por 0.5 (se reduce)
          - risk_multiplier = 0.0 → risk = 1.0   → utility se divide por 1 (mínimo)

        En HIBERNATION: utility = 0, threshold = 1.0 (nunca tradea)

        Args:
            probability: Probabilidad de la señal (0-1)
            expected_reward_ratio: Ratio reward/risk esperado
            market_quality: Calidad del mercado (0-1)
            risk_multiplier: Multiplicador de riesgo del sistema (0-1)
            is_hibernation: Si el sistema está en hibernación

        Returns:
            Tuple[float, float]: (utility_score, dynamic_threshold)
        """
        # ─── HIBERNATION: utilidad cero, umbral máximo ───
        if is_hibernation:
            return 0.0, 1.0

        # ─── Utility Score ───
        # Fórmula: utility = (probability * expected_reward * market_quality) / risk
        #
        # probability:       0-1  (qué tan segura es la señal)
        # expected_reward:   0-N  (qué tan buena es la relación reward/risk)
        # market_quality:    0-1  (qué tan bueno está el mercado)
        # risk:              0-1  (inversamente proporcional a risk_multiplier)
        #
        # Rango típico: 0.0 (pésimo) → ~3.0+ (excelente)

        # risk = 1 / (1 + risk_multiplier * 10)
        # Cuando risk_multiplier = 1.0 (sistema saludable):
        #   risk = 1/11 ≈ 0.091 → utility se multiplica por ~11
        # Cuando risk_multiplier = 0.1 (sistema crítico):
        #   risk = 1/2 = 0.5 → utility se multiplica por 2
        # Cuando risk_multiplier = 0.0 (hibernación):
        #   risk = 1.0 → utility se multiplica por 1
        risk = 1.0 / (1.0 + risk_multiplier * 10.0)

        utility = (
            probability *
            expected_reward_ratio *
            market_quality /
            max(risk, 1e-10)
        )

        # ─── Umbral Dinámico ───
        # El umbral se adapta al estado del mercado y del sistema
        base_threshold = self.config["base_utility_threshold"]

        # Ajustar por calidad del mercado
        if market_quality >= 0.85:  # GOLDEN_STATE
            threshold_adj = -0.20  # Más fácil aprobar
        elif market_quality >= 0.60:  # FAVORABLE
            threshold_adj = -0.08
        elif market_quality <= 0.35:  # TOXICO
            threshold_adj = 0.25  # Más difícil aprobar
        else:  # NORMAL
            threshold_adj = 0.0

        # Ajustar por riesgo del sistema
        if risk_multiplier <= 0.1:  # CRITICAL
            threshold_adj += 0.25
        elif risk_multiplier <= 0.3:  # STRESS
            threshold_adj += 0.15
        elif risk_multiplier <= 0.6:  # CAUTION
            threshold_adj += 0.08

        dynamic_threshold = base_threshold + threshold_adj

        # Asegurar rango [min, max]
        dynamic_threshold = max(
            self.config["min_utility_threshold"],
            min(self.config["max_utility_threshold"], dynamic_threshold)
        )

        return utility, dynamic_threshold

    def _adjust_parameters(
        self,
        market_diagnosis: MarketDiagnosis,
        system_diagnosis: SystemDiagnosis,
        utility_score: float,
        dynamic_threshold: float,
    ) -> Dict:
        """
        Ajusta los parámetros de trading dentro de los límites establecidos.

        NOTA: La confianza ajustada es SOLO para visualización/logging.
        La decisión real se basa en utility_score > dynamic_threshold.

        Args:
            market_diagnosis: Diagnóstico del mercado
            system_diagnosis: Diagnóstico del sistema
            utility_score: Utility score calculado
            dynamic_threshold: Umbral dinámico

        Returns:
            Dict con parámetros ajustados
        """
        limits = self.LIMITS

        # ─── Confidence Threshold (SOLO VISUAL) ───
        # La confianza es decorativa. La utility es la métrica maestra.
        # Se calcula suavemente para reflejar el contexto en el dashboard.
        base_conf = self.config["default_confidence_threshold"]

        if market_diagnosis.market_state == MarketState.GOLDEN_STATE:
            conf_adj = -0.08
        elif market_diagnosis.market_state == MarketState.FAVORABLE:
            conf_adj = -0.03
        elif market_diagnosis.market_state == MarketState.TOXICO:
            conf_adj = 0.12
        else:
            conf_adj = 0.0

        if system_diagnosis.system_alert == SystemAlert.HIBERNATION:
            conf_adj = 0.20  # Máxima exigencia visual
        elif system_diagnosis.system_alert == SystemAlert.CRITICAL:
            conf_adj += 0.15
        elif system_diagnosis.system_alert == SystemAlert.STRESS:
            conf_adj += 0.08
        elif system_diagnosis.system_alert == SystemAlert.CAUTION:
            conf_adj += 0.03

        adjusted_confidence = base_conf + conf_adj
        adjusted_confidence = max(
            limits["confidence_threshold"]["min"],
            min(limits["confidence_threshold"]["max"], adjusted_confidence)
        )

        # ─── Risk Per Trade ───
        base_risk = self.config["default_risk_per_trade"]

        # En HIBERNATION, riesgo CERO
        if system_diagnosis.system_alert == SystemAlert.HIBERNATION:
            adjusted_risk = limits["risk_per_trade"]["min"]
        else:
            risk_adj = system_diagnosis.risk_multiplier

            # Ajustar por calidad del mercado
            if market_diagnosis.market_state == MarketState.GOLDEN_STATE:
                risk_adj *= 1.3
            elif market_diagnosis.market_state == MarketState.TOXICO:
                risk_adj *= 0.5

            # Ajustar por utility (si utility es alta, podemos arriesgar más)
            if utility_score > dynamic_threshold * 1.5:
                risk_adj *= 1.2
            elif utility_score < dynamic_threshold * 0.7:
                risk_adj *= 0.7

            adjusted_risk = base_risk * risk_adj
            adjusted_risk = max(
                limits["risk_per_trade"]["min"],
                min(limits["risk_per_trade"]["max"], adjusted_risk)
            )

        # ─── SL ATR ───
        base_sl = self.config["default_sl_atr"]

        if market_diagnosis.volatility_regime == "EXTREME":
            sl_adj = 1.5
        elif market_diagnosis.volatility_regime == "HIGH":
            sl_adj = 1.2
        elif market_diagnosis.volatility_regime == "LOW":
            sl_adj = 0.8
        else:
            sl_adj = 1.0

        if system_diagnosis.system_alert == SystemAlert.CRITICAL:
            sl_adj *= 1.3
        elif system_diagnosis.system_alert == SystemAlert.STRESS:
            sl_adj *= 1.15

        adjusted_sl = base_sl * sl_adj
        adjusted_sl = max(
            limits["sl_atr"]["min"],
            min(limits["sl_atr"]["max"], adjusted_sl)
        )

        # ─── TP ATR ───
        base_tp = self.config["default_tp_atr"]

        if market_diagnosis.trend_strength == "EXTREME":
            tp_adj = 1.3
        elif market_diagnosis.trend_strength == "STRONG":
            tp_adj = 1.15
        elif market_diagnosis.trend_strength == "WEAK":
            tp_adj = 0.8
        else:
            tp_adj = 1.0

        if market_diagnosis.market_state == MarketState.GOLDEN_STATE:
            tp_adj *= 1.2
        elif market_diagnosis.market_state == MarketState.TOXICO:
            tp_adj *= 0.7

        adjusted_tp = base_tp * tp_adj
        adjusted_tp = max(
            limits["tp_atr"]["min"],
            min(limits["tp_atr"]["max"], adjusted_tp)
        )

        return {
            "confidence_threshold": round(adjusted_confidence, 3),
            "risk_per_trade": round(adjusted_risk, 4),
            "sl_atr": round(adjusted_sl, 2),
            "tp_atr": round(adjusted_tp, 2),
        }

    # ══════════════════════════════════════════
    # EVALUACIÓN COMPLETA
    # ══════════════════════════════════════════

    def evaluate(
        self,
        # Señal del Sniper
        probability: float,
        expected_reward_ratio: float,  # TP/SL ratio
        # Capa 1 — Datos del mercado
        atr_current: float,
        atr_median: float,
        volume_delta: float,
        momentum_3h: float,
        momentum_6h: float,
        divergence: float,
        hour_utc: Optional[int] = None,
        rejection_speed: float = 0.0,
        tick_vol_std: float = 0.0,
        # Capa 2 — Datos del sistema
        win_rate_24h: float = 0.5,
        drawdown: float = 0.0,
        consecutive_losses: int = 0,
        latency_ms: float = 0.0,
        brain_confidence: float = 0.5,
    ) -> UtilityDecision:
        """
        Evaluación completa del Meta-Brain V10 (3 Capas + HIBERNATION).

        La UTILITY es la métrica maestra de decisión.
        La confianza es SOLO para visualización/logging/dashboard.

        Args:
            probability: Probabilidad de la señal (0-1)
            expected_reward_ratio: Ratio reward/risk (TP/SL)
            atr_current: ATR actual
            atr_median: ATR mediano histórico
            volume_delta: Volume delta (-1 a 1)
            momentum_3h: Momentum 3h
            momentum_6h: Momentum 6h
            divergence: Divergencia cross-asset
            hour_utc: Hora UTC (auto si None)
            rejection_speed: Velocidad de rechazo
            tick_vol_std: Desviación std del volumen de ticks
            win_rate_24h: Win rate últimas 24h
            drawdown: Drawdown actual
            consecutive_losses: Rachas de pérdidas
            latency_ms: Latencia de inferencia
            brain_confidence: Confianza media del cerebro

        Returns:
            UtilityDecision con la decisión final
        """
        self.state["total_evaluations"] += 1

        if hour_utc is None:
            hour_utc = datetime.now(timezone.utc).hour

        # ─── CAPA 1: Diagnosticar Mercado ───
        market_diagnosis = self._diagnose_market(
            atr_current=atr_current,
            atr_median=atr_median,
            volume_delta=volume_delta,
            momentum_3h=momentum_3h,
            momentum_6h=momentum_6h,
            divergence=divergence,
            hour_utc=hour_utc,
            rejection_speed=rejection_speed,
            tick_vol_std=tick_vol_std,
        )

        # ─── CAPA 2: Diagnosticar Sistema ───
        system_diagnosis = self._diagnose_system(
            win_rate_24h=win_rate_24h,
            drawdown=drawdown,
            consecutive_losses=consecutive_losses,
            latency_ms=latency_ms,
            brain_confidence=brain_confidence,
        )

        # ─── Verificar HIBERNATION ───
        is_hibernation = system_diagnosis.system_alert == SystemAlert.HIBERNATION
        if is_hibernation:
            self.state["total_hibernation_events"] += 1

        # ─── CAPA 3: Calcular Utilidad ───
        utility_score, dynamic_threshold = self._calculate_utility(
            probability=probability,
            expected_reward_ratio=expected_reward_ratio,
            market_quality=market_diagnosis.market_quality,
            risk_multiplier=system_diagnosis.risk_multiplier,
            is_hibernation=is_hibernation,
        )

        # ─── Ajustar Parámetros ───
        adjusted_params = self._adjust_parameters(
            market_diagnosis=market_diagnosis,
            system_diagnosis=system_diagnosis,
            utility_score=utility_score,
            dynamic_threshold=dynamic_threshold,
        )

        # ─── Decisión Final (basada en UTILITY, NO en confianza) ───
        should_trade = utility_score > dynamic_threshold

        # ─── Construir razón ───
        if is_hibernation:
            reason_parts = [
                "🧊 HIBERNATION ACTIVADO",
                f"Utility={utility_score:.2f} (forzado a 0)",
                f"Mercado={market_diagnosis.market_state.value}",
                f"Sistema={system_diagnosis.system_alert.value}",
            ]
            reason = " | ".join(reason_parts)
            self.state["total_trades_rejected"] += 1
        elif should_trade:
            reason_parts = [
                f"✅ UTILITY={utility_score:.2f} > UMBRAL={dynamic_threshold:.2f}",
                f"Mercado={market_diagnosis.market_state.value}",
                f"Sistema={system_diagnosis.system_alert.value}",
            ]
            reason = " | ".join(reason_parts)
            self.state["total_trades_approved"] += 1
        else:
            reason_parts = [
                f"❌ UTILITY={utility_score:.2f} ≤ UMBRAL={dynamic_threshold:.2f}",
                f"Mercado={market_diagnosis.market_state.value}",
                f"Sistema={system_diagnosis.system_alert.value}",
            ]
            reason = " | ".join(reason_parts)
            self.state["total_trades_rejected"] += 1

        # ─── Construir Decisión ───
        decision = UtilityDecision(
            utility_score=round(utility_score, 4),
            threshold=round(dynamic_threshold, 4),
            should_trade=should_trade,
            adjusted_confidence=adjusted_params["confidence_threshold"],
            adjusted_risk_pct=adjusted_params["risk_per_trade"],
            adjusted_sl_atr=adjusted_params["sl_atr"],
            adjusted_tp_atr=adjusted_params["tp_atr"],
            reason=reason,
            details={
                "market_state": market_diagnosis.market_state.value,
                "system_alert": system_diagnosis.system_alert.value,
                "market_quality": round(market_diagnosis.market_quality, 3),
                "risk_multiplier": round(system_diagnosis.risk_multiplier, 3),
                "probability": round(probability, 3),
                "expected_reward_ratio": round(expected_reward_ratio, 2),
                "is_hibernation": is_hibernation,
                "hibernation_reasons": (
                    system_diagnosis.details.get("hibernation_reasons", [])
                    if is_hibernation else []
                ),
            }
        )

        # ─── Actualizar estado interno ───
        self.state["last_market_diagnosis"] = market_diagnosis
        self.state["last_system_diagnosis"] = system_diagnosis
        self.state["last_utility_decision"] = decision

        # ─── Logging ───
        if is_hibernation:
            logger.info(
                f"🧊 CAPA 3 — HIBERNATION: NO TRADE | "
                f"Utility=0.000 (forzado) | "
                f"Razones: {', '.join(system_diagnosis.details.get('hibernation_reasons', []))}"
            )
        else:
            icon = "✅" if should_trade else "❌"
            logger.info(
                f"{icon} CAPA 3 — DECISIÓN: {'TRADE' if should_trade else 'NO TRADE'} | "
                f"Utility={utility_score:.3f} vs Threshold={dynamic_threshold:.3f} | "
                f"Conf={adjusted_params['confidence_threshold']:.2f} (visual) | "
                f"Risk={adjusted_params['risk_per_trade']*100:.2f}% | "
                f"SL={adjusted_params['sl_atr']:.1f}ATR | TP={adjusted_params['tp_atr']:.1f}ATR"
            )

        return decision

    # ══════════════════════════════════════════
    # REPORTE DE RESULTADOS
    # ══════════════════════════════════════════

    def report_trade_result(self, pnl: float):
        """
        Reporta el resultado de un trade para que el Meta-Brain aprenda.

        Args:
            pnl: Profit/Loss del trade en USD
        """
        self.state["meta_trades"] += 1
        if pnl > 0:
            self.state["meta_wins"] += 1

        # Actualizar win rate
        if self.state["meta_trades"] > 0:
            self.state["meta_win_rate"] = (
                self.state["meta_wins"] / self.state["meta_trades"]
            )

        # Guardar en historial
        self._trade_history.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "pnl": pnl,
            "market_state": (
                self.state["last_market_diagnosis"].market_state.value
                if self.state["last_market_diagnosis"] else "UNKNOWN"
            ),
            "system_alert": (
                self.state["last_system_diagnosis"].system_alert.value
                if self.state["last_system_diagnosis"] else "UNKNOWN"
            ),
            "utility_score": (
                self.state["last_utility_decision"].utility_score
                if self.state["last_utility_decision"] else 0.0
            ),
        })

        # Mantener solo últimos 1000 trades
        if len(self._trade_history) > 1000:
            self._trade_history = self._trade_history[-1000:]

        logger.info(
            f"📈 META-BRAIN: Trade #{self.state['meta_trades']} | "
            f"PNL=${pnl:.2f} | Meta WR={self.state['meta_win_rate']:.1%}"
        )

    # ══════════════════════════════════════════
    # FASE 10.2 — MEMORIA OPERATIVA
    # ══════════════════════════════════════════

    def _load_feedback(self):
        """
        Carga el historial de feedback desde el archivo JSON.
        Si el archivo no existe, inicializa con lista vacía.
        """
        try:
            if os.path.exists(self._feedback_path):
                with open(self._feedback_path, "r") as f:
                    self._feedback = json.load(f)
                logger.info(f"📂 Feedback cargado: {len(self._feedback)} registros")
            else:
                self._feedback = []
                logger.info("📂 No hay feedback previo. Iniciando nuevo historial.")
        except Exception as e:
            logger.warning(f"⚠️ Error cargando feedback: {e}")
            self._feedback = []

    def _save_feedback(self):
        """
        Guarda el historial de feedback en el archivo JSON.
        """
        try:
            os.makedirs(os.path.dirname(self._feedback_path), exist_ok=True)
            with open(self._feedback_path, "w") as f:
                json.dump(self._feedback, f, indent=2, default=str)
            logger.debug(f"💾 Feedback guardado: {len(self._feedback)} registros")
        except Exception as e:
            logger.warning(f"⚠️ Error guardando feedback: {e}")

    def record_result(
        self,
        pnl: float,
        expected_utility: float,
        realized_utility: Optional[float] = None,
        market_state: Optional[str] = None,
        system_alert: Optional[str] = None,
        probability: float = 0.0,
        expected_reward_ratio: float = 0.0,
        risk_pct: float = 0.0,
        sl_atr: float = 0.0,
        tp_atr: float = 0.0,
        r_multiple: Optional[float] = None,
    ):
        """
        FASE 10.3: Registra el resultado de un trade con R-multiple y utilidad.

        Ahora incluye r_multiple para ponderar wins por su calidad real.
        Un win de +3.5R no pesa igual que uno de +0.2R en la calibración.

        Args:
            pnl: Profit/Loss del trade en USD
            expected_utility: Utility score esperado (antes del trade)
            realized_utility: Utility score realizado (calculado post-trade)
            market_state: Estado del mercado al momento del trade
            system_alert: Alerta del sistema al momento del trade
            probability: Probabilidad de la señal
            expected_reward_ratio: Ratio reward/risk esperado
            risk_pct: Porcentaje de riesgo usado
            sl_atr: Stop Loss en ATR
            tp_atr: Take Profit en ATR
            r_multiple: R múltiple realizado (e.g., 2.4 = ganó 2.4x el riesgo)
        """
        # Determinar realized_utility si no se provee
        if realized_utility is None:
            realized_utility = expected_utility * (1.0 + pnl / 100.0) if pnl > 0 else expected_utility * (1.0 + pnl / 200.0)
            realized_utility = max(-1.0, min(3.0, realized_utility))

        # Calcular r_multiple si no se provee
        if r_multiple is None and risk_pct > 0 and pnl != 0:
            # Asumimos que el riesgo en USD = risk_pct * 10000 (capital simbólico)
            risk_usd = risk_pct * 10000
            r_multiple = pnl / risk_usd if risk_usd != 0 else 0.0
            r_multiple = max(-3.0, min(10.0, r_multiple))
        elif r_multiple is None:
            r_multiple = 0.0

        # Obtener estado del mercado/sistema de la última evaluación si no se provee
        if market_state is None and self.state["last_market_diagnosis"]:
            market_state = self.state["last_market_diagnosis"].market_state.value
        if system_alert is None and self.state["last_system_diagnosis"]:
            system_alert = self.state["last_system_diagnosis"].system_alert.value

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "pnl": round(pnl, 2),
            "r_multiple": round(r_multiple, 2),
            "expected_utility": round(expected_utility, 4),
            "realized_utility": round(realized_utility, 4),
            "utility_error": round(realized_utility - expected_utility, 4),
            "market_state": market_state or "UNKNOWN",
            "system_alert": system_alert or "UNKNOWN",
            "probability": round(probability, 3),
            "expected_reward_ratio": round(expected_reward_ratio, 2),
            "risk_pct": round(risk_pct, 4),
            "sl_atr": round(sl_atr, 2),
            "tp_atr": round(tp_atr, 2),
            "was_win": pnl > 0,
        }

        self._feedback.append(record)

        # Mantener solo últimos 500 registros
        if len(self._feedback) > 500:
            self._feedback = self._feedback[-500:]

        # Actualizar calibración por estado de mercado (ponderada por R-multiple)
        ms_key = market_state or "UNKNOWN"
        if ms_key in self._calibration:
            cal = self._calibration[ms_key]
            cal["trades"] += 1
            if pnl > 0:
                cal["wins"] += 1
            cal["wr"] = cal["wins"] / max(cal["trades"], 1)

            # FASE 10.3: Acumular R-multiple para calibración ponderada
            cal["total_r"] = cal.get("total_r", 0.0) + r_multiple
            cal["avg_r"] = cal["total_r"] / max(cal["trades"], 1)

        # Persistir
        self._save_feedback()

        # Recalibrar si hay suficientes datos
        self._recalibrate_from_feedback()

        logger.info(
            f"📝 FEEDBACK: PNL=${pnl:.2f} | R={r_multiple:+.2f} | "
            f"ExpUtil={expected_utility:.3f} → RealUtil={realized_utility:.3f} | "
            f"Error={record['utility_error']:.3f} | "
            f"Estado={ms_key}"
        )

    def _recalibrate_from_feedback(self):
        """
        FASE 10.3: Recalibra los ajustes del Meta-Brain basado en feedback histórico
        PONDERADO por R-multiple.

        En lugar de solo mirar WR binario (ganó/perdió), ahora mira:
        - avg_r: R-multiple promedio (un win de +3.5R pesa más que uno de +0.2R)
        - WR combinado con avg_r para determinar la calidad real del rendimiento

        Mínimo de trades para recalibrar: 10 (vs 5 en V10.2).
        En producción se recomienda 20.

        Los ajustes se aplican suavemente (factor 0.3) para evitar oscilaciones.
        """
        for state_key, cal in self._calibration.items():
            if cal["trades"] < 10:
                continue  # FASE 10.3: mínimo 10 trades para recalibrar

            wr = cal["wr"]
            avg_r = cal.get("avg_r", 0.0)

            # ─── Score compuesto: WR + R-multiple ───
            # Un WR de 60% con avg_r=+0.8 es mejor que WR 60% con avg_r=+0.2
            # Fórmula: quality_score = wr * (1 + avg_r * 0.5)
            #   avg_r=+2.0 → quality_score = wr * 2.0  (excelente)
            #   avg_r=+0.5 → quality_score = wr * 1.25 (bueno)
            #   avg_r=-0.5 → quality_score = wr * 0.75 (malo)
            quality_score = wr * (1.0 + avg_r * 0.5)
            quality_score = max(0.0, min(2.0, quality_score))

            # ─── Determinar targets basados en quality_score ───
            if quality_score > 0.80:
                # Rendimiento excelente (WR alto Y R-multiple bueno)
                # → Confiar más, reducir threshold, aumentar riesgo
                target_mq = 1.05
                target_th = -0.03
                target_rk = 1.05
            elif quality_score > 0.55:
                # Rendimiento decente
                # → Ajustes moderados
                target_mq = 1.02
                target_th = -0.01
                target_rk = 1.02
            elif quality_score > 0.35:
                # Rendimiento neutral
                # → Mantener defaults
                target_mq = 1.0
                target_th = 0.0
                target_rk = 1.0
            elif quality_score > 0.15:
                # Rendimiento pobre
                # → Ser más conservadores
                target_mq = 0.92
                target_th = 0.03
                target_rk = 0.88
            else:
                # Rendimiento muy pobre
                # → Máxima precaución
                target_mq = 0.85
                target_th = 0.07
                target_rk = 0.75

            # Aplicar suavemente (factor de aprendizaje = 0.3)
            cal["mq_adj"] = cal["mq_adj"] * 0.7 + target_mq * 0.3
            cal["th_adj"] = cal["th_adj"] * 0.7 + target_th * 0.3
            cal["rk_adj"] = cal["rk_adj"] * 0.7 + target_rk * 0.3

            # Limitar rangos
            cal["mq_adj"] = max(0.7, min(1.3, cal["mq_adj"]))
            cal["th_adj"] = max(-0.10, min(0.15, cal["th_adj"]))
            cal["rk_adj"] = max(0.5, min(1.5, cal["rk_adj"]))

            logger.debug(
                f"🔄 Calibración [{state_key}]: "
                f"WR={wr:.1%} | avg_R={avg_r:+.2f} | "
                f"QScore={quality_score:.2f} ({cal['trades']} trades) | "
                f"mq_adj={cal['mq_adj']:.2f} | th_adj={cal['th_adj']:.2f} | rk_adj={cal['rk_adj']:.2f}"
            )

    def get_performance_summary(self) -> Dict:
        """
        FASE 10.2: Retorna un resumen de rendimiento del Meta-Brain.

        Incluye:
        - WR global y por estado de mercado
        - Error de utilidad promedio (expected vs realized)
        - Calibración actual por estado
        - Últimos N trades
        - Métricas extendidas para integración con Orchestrator

        Returns:
            Dict con el resumen de rendimiento
        """
        total = len(self._feedback)
        if total == 0:
            return {
                "total_trades": 0,
                "global_win_rate": 0.0,
                "win_rate": 0.0,  # alias para compatibilidad
                "avg_utility_error": 0.0,
                "by_market_state": {},
                "calibration": self._calibration,
                "recent_trades": [],
                "avg_r": 0.0,
                "expectancy": 0.0,
                "profit_factor": 0.0,
                "total_vetoes": 0,
                "max_drawdown": 0.0,
            }

        wins = sum(1 for r in self._feedback if r["was_win"])
        utility_errors = [r["utility_error"] for r in self._feedback]
        win_rate = round(wins / max(total, 1), 4)

        # Calcular R múltiple promedio (avg_r)
        r_values = [r.get("r_multiple", 0.0) for r in self._feedback]
        avg_r = round(sum(r_values) / max(len(r_values), 1), 4)

        # Calcular expectancy
        expectancy = round(win_rate * avg_r - (1 - win_rate) * 1.0, 4)

        # Calcular profit factor
        gross_profit = sum(r.get("r_multiple", 0.0) for r in self._feedback if r.get("r_multiple", 0.0) > 0)
        gross_loss = abs(sum(r.get("r_multiple", 0.0) for r in self._feedback if r.get("r_multiple", 0.0) < 0))
        profit_factor = round(gross_profit / max(gross_loss, 0.0001), 4)

        # Vetoes y drawdown desde el estado interno
        total_vetoes = self.state.get("total_trades_rejected", 0)
        max_drawdown = self.state.get("max_drawdown", 0.0)

        # WR por estado de mercado
        by_state = {}
        for r in self._feedback:
            ms = r.get("market_state", "UNKNOWN")
            if ms not in by_state:
                by_state[ms] = {"trades": 0, "wins": 0}
            by_state[ms]["trades"] += 1
            if r["was_win"]:
                by_state[ms]["wins"] += 1

        for ms, data in by_state.items():
            data["win_rate"] = round(data["wins"] / max(data["trades"], 1), 4)

        # Últimos 20 trades
        recent = sorted(self._feedback, key=lambda x: x["timestamp"], reverse=True)[:20]

        return {
            "total_trades": total,
            "global_win_rate": win_rate,
            "win_rate": win_rate,  # alias para compatibilidad con stratum_v8_master_live.py
            "avg_utility_error": round(sum(utility_errors) / max(len(utility_errors), 1), 4),
            "by_market_state": by_state,
            "calibration": self._calibration,
            "recent_trades": recent,
            "avg_r": avg_r,
            "expectancy": expectancy,
            "profit_factor": profit_factor,
            "total_vetoes": total_vetoes,
            "max_drawdown": max_drawdown,
        }

    # ══════════════════════════════════════════
    # MÉTODOS DE CONSULTA
    # ══════════════════════════════════════════

    def generate_dynamic_config(self) -> dict:
        """
        Genera la configuración dinámica que el Orchestrator puede consumir.

        Este método traduce el estado actual del Meta-Brain en parámetros
        accionables para el Execution Engine y el Strategy Engine.

        Returns:
            Dict con la configuración dinámica:
            {
            "meta_brain_version": "V10.3",
                "timestamp": "2026-06-09T...",
                "market_state": "GOLDEN_STATE",
                "system_alert": "NORMAL",
                "utility_score": 2.45,
                "should_trade": True,
                "params": {
                    "confidence_threshold": 0.55,
                    "risk_per_trade": 0.015,
                    "sl_atr": 1.5,
                    "tp_atr": 2.5
                },
                "limits": {...},
                "hibernation": False
            }
        """
        decision = self.state.get("last_utility_decision")
        market = self.state.get("last_market_diagnosis")
        system = self.state.get("last_system_diagnosis")

        # Detectar hibernación
        is_hibernation = (
            system is not None and
            system.system_alert == SystemAlert.HIBERNATION
        )

        # Parámetros por defecto si no hay decisión aún
        if decision is None:
            params = {
                "confidence_threshold": self.config["default_confidence_threshold"],
                "risk_per_trade": self.config["default_risk_per_trade"],
                "sl_atr": self.config["default_sl_atr"],
                "tp_atr": self.config["default_tp_atr"],
            }
            should_trade = False
            utility_score = 0.0
        else:
            params = {
                "confidence_threshold": decision.adjusted_confidence,
                "risk_per_trade": decision.adjusted_risk_pct,
                "sl_atr": decision.adjusted_sl_atr,
                "tp_atr": decision.adjusted_tp_atr,
            }
            should_trade = decision.should_trade
            utility_score = decision.utility_score

        config = {
            "meta_brain_version": "V10.3",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "market_state": market.market_state.value if market else "UNKNOWN",
            "system_alert": system.system_alert.value if system else "UNKNOWN",
            "utility_score": round(utility_score, 4),
            "should_trade": should_trade,
            "hibernation": is_hibernation,
            "params": params,
            "limits": {
                "confidence_threshold": {
                    "min": self.LIMITS["confidence_threshold"]["min"],
                    "max": self.LIMITS["confidence_threshold"]["max"],
                },
                "risk_per_trade": {
                    "min": self.LIMITS["risk_per_trade"]["min"],
                    "max": self.LIMITS["risk_per_trade"]["max"],
                },
                "sl_atr": {
                    "min": self.LIMITS["sl_atr"]["min"],
                    "max": self.LIMITS["sl_atr"]["max"],
                },
                "tp_atr": {
                    "min": self.LIMITS["tp_atr"]["min"],
                    "max": self.LIMITS["tp_atr"]["max"],
                },
            },
            "market_quality": round(market.market_quality, 3) if market else 0.0,
            "risk_multiplier": round(system.risk_multiplier, 3) if system else 1.0,
        }

        return config

    def get_status(self) -> dict:
        """
        Retorna el estado completo del Meta-Brain para el War Room.

        Returns:
            Dict con todo el estado del Meta-Brain
        """
        market = self.state["last_market_diagnosis"]
        system = self.state["last_system_diagnosis"]
        decision = self.state["last_utility_decision"]

        return {
            "version": "V10",
            "total_evaluations": self.state["total_evaluations"],
            "total_trades_approved": self.state["total_trades_approved"],
            "total_trades_rejected": self.state["total_trades_rejected"],
            "total_hibernation_events": self.state["total_hibernation_events"],
            "meta_win_rate": round(self.state["meta_win_rate"], 4),
            "meta_trades": self.state["meta_trades"],
            "market": {
                "state": market.market_state.value if market else "UNKNOWN",
                "quality": round(market.market_quality, 3) if market else 0.0,
                "volatility": market.volatility_regime if market else "UNKNOWN",
                "liquidity": market.liquidity_regime if market else "UNKNOWN",
                "trend": market.trend_strength if market else "UNKNOWN",
                "cross_asset": market.cross_asset_alignment if market else "UNKNOWN",
                "session": market.session if market else "UNKNOWN",
            } if market else {},
            "system": {
                "alert": system.system_alert.value if system else "UNKNOWN",
                "risk_multiplier": round(system.risk_multiplier, 3) if system else 1.0,
                "win_rate_24h": round(system.win_rate_24h, 3) if system else 0.0,
                "drawdown": round(system.drawdown, 3) if system else 0.0,
                "consecutive_losses": system.consecutive_losses if system else 0,
                "latency_ms": round(system.latency_ms, 1) if system else 0.0,
                "brain_confidence": round(system.brain_confidence, 3) if system else 0.0,
            } if system else {},
            "decision": {
                "should_trade": decision.should_trade if decision else False,
                "utility_score": round(decision.utility_score, 4) if decision else 0.0,
                "threshold": round(decision.threshold, 4) if decision else 0.0,
                "adjusted_confidence": decision.adjusted_confidence if decision else 0.55,
                "adjusted_risk_pct": decision.adjusted_risk_pct if decision else 0.01,
                "adjusted_sl_atr": decision.adjusted_sl_atr if decision else 1.5,
                "adjusted_tp_atr": decision.adjusted_tp_atr if decision else 2.0,
                "reason": decision.reason if decision else "Sin evaluaciones aún",
            } if decision else {},
            "limits": {
                "confidence_threshold": self.LIMITS["confidence_threshold"],
                "risk_per_trade": self.LIMITS["risk_per_trade"],
                "sl_atr": self.LIMITS["sl_atr"],
                "tp_atr": self.LIMITS["tp_atr"],
            },
        }

    def get_market_state(self) -> Optional[MarketState]:
        """Retorna el último estado del mercado diagnosticado."""
        if self.state["last_market_diagnosis"]:
            return self.state["last_market_diagnosis"].market_state
        return None

    def get_system_alert(self) -> Optional[SystemAlert]:
        """Retorna la última alerta del sistema."""
        if self.state["last_system_diagnosis"]:
            return self.state["last_system_diagnosis"].system_alert
        return None

    def get_utility_score(self) -> float:
        """Retorna el último utility score calculado."""
        if self.state["last_utility_decision"]:
            return self.state["last_utility_decision"].utility_score
        return 0.0

    def summary(self) -> str:
        """Retorna un resumen formateado del estado del Meta-Brain."""
        status = self.get_status()

        market_icons = {
            "GOLDEN_STATE": "🟣",
            "FAVORABLE": "🟢",
            "NORMAL": "🟡",
            "TOXICO": "🔴",
        }
        system_icons = {
            "NORMAL": "🟢",
            "CAUTION": "🟡",
            "STRESS": "🟠",
            "CRITICAL": "🔴",
            "HIBERNATION": "🧊",
        }

        lines = [
            "\n" + "=" * 70,
            "🧠 META-BRAIN V10 — RESUMEN",
            "=" * 70,
        ]

        # Capa 1
        if status.get("market"):
            m = status["market"]
            icon = market_icons.get(m["state"], "❓")
            lines.extend([
                f"\n📊 CAPA 1 — ESTADO DEL MERCADO: {icon} {m['state']}",
                f"   Calidad: {m['quality']:.2f} | Vol: {m['volatility']} | "
                f"Liq: {m['liquidity']} | Trend: {m['trend']} | "
                f"Cross: {m['cross_asset']} | Sesión: {m['session']}",
            ])

        # Capa 2
        if status.get("system"):
            s = status["system"]
            icon = system_icons.get(s["alert"], "❓")
            lines.extend([
                f"\n🖥️ CAPA 2 — ESTADO DEL SISTEMA: {icon} {s['alert']}",
                f"   WR 24h: {s['win_rate_24h']:.1%} | DD: {s['drawdown']:.1%} | "
                f"Racha: {s['consecutive_losses']} | Lat: {s['latency_ms']:.0f}ms | "
                f"Conf: {s['brain_confidence']:.2f} | RiskMult: {s['risk_multiplier']:.2f}",
            ])

        # Capa 3
        if status.get("decision"):
            d = status["decision"]
            trade_icon = "✅" if d["should_trade"] else "❌"
            lines.extend([
                f"\n⚙️ CAPA 3 — MOTOR DE UTILIDAD: {trade_icon}",
                f"   Utility: {d['utility_score']:.4f} vs Threshold: {d['threshold']:.4f} "
                f"(métrica maestra: UTILITY)",
                f"   Confianza: {d['adjusted_confidence']:.2f} (SOLO VISUAL) | "
                f"Riesgo: {d['adjusted_risk_pct']*100:.2f}% | "
                f"SL: {d['adjusted_sl_atr']:.1f}ATR | TP: {d['adjusted_tp_atr']:.1f}ATR",
                f"   Razón: {d['reason']}",
            ])

        # Estadísticas globales
        lines.extend([
            f"\n📈 ESTADÍSTICAS GLOBALES:",
            f"   Evaluaciones: {status['total_evaluations']} | "
            f"Aprobados: {status['total_trades_approved']} | "
            f"Rechazados: {status['total_trades_rejected']} | "
            f"Hibernaciones: {status['total_hibernation_events']} | "
            f"Meta WR: {status['meta_win_rate']:.1%}",
        ])

        lines.append("\n" + "=" * 70)
        return "\n".join(lines)


    # ══════════════════════════════════════════
    # MÉTODOS DE INTEGRACIÓN (FASE 10.4)
    # ══════════════════════════════════════════

    def update_system_state(
        self,
        win_rate_24h: Optional[float] = None,
        drawdown: Optional[float] = None,
        consecutive_losses: Optional[int] = None,
        latency_ms: Optional[float] = None,
        brain_confidence: Optional[float] = None,
    ):
        """
        Actualiza el estado del sistema para la Capa 2.

        Útil cuando el Orchestrator quiere actualizar las métricas
        del sistema sin hacer una evaluación completa.

        Args:
            win_rate_24h: Win rate últimas 24h (0-1)
            drawdown: Drawdown actual (0-1)
            consecutive_losses: Rachas de pérdidas
            latency_ms: Latencia de inferencia en ms
            brain_confidence: Confianza media del cerebro (0-1)
        """
        if win_rate_24h is not None:
            self._cached_win_rate = win_rate_24h
        if drawdown is not None:
            self._cached_drawdown = drawdown
        if consecutive_losses is not None:
            self._cached_consecutive_losses = consecutive_losses
        if latency_ms is not None:
            self._cached_latency = latency_ms
        if brain_confidence is not None:
            self._cached_brain_confidence = brain_confidence

        logger.debug(
            f"🔄 System state updated: WR={self._cached_win_rate:.1%} | "
            f"DD={self._cached_drawdown:.1%} | "
            f"Racha={self._cached_consecutive_losses} | "
            f"Lat={self._cached_latency:.0f}ms | "
            f"Conf={self._cached_brain_confidence:.2f}"
        )

    def save_state(self, filepath: Optional[str] = None) -> str:
        """
        Guarda el estado completo del Meta-Brain en un archivo JSON.

        Args:
            filepath: Ruta del archivo (opcional, por defecto data/meta_brain_state.json)

        Returns:
            str: Ruta del archivo guardado
        """
        if filepath is None:
            filepath = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "data", "meta_brain_state.json"
            )

        state_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": "V10.3",
            "config": self.config,
            "state": self.state,
            "calibration": self._calibration,
            "cached_system": {
                "win_rate_24h": getattr(self, "_cached_win_rate", 0.5),
                "drawdown": getattr(self, "_cached_drawdown", 0.0),
                "consecutive_losses": getattr(self, "_cached_consecutive_losses", 0),
                "latency_ms": getattr(self, "_cached_latency", 0.0),
                "brain_confidence": getattr(self, "_cached_brain_confidence", 0.5),
            },
            "last_market_diagnosis": (
                {
                    "market_state": self.state["last_market_diagnosis"].market_state.value,
                    "market_quality": self.state["last_market_diagnosis"].market_quality,
                    "volatility_regime": self.state["last_market_diagnosis"].volatility_regime,
                    "liquidity_regime": self.state["last_market_diagnosis"].liquidity_regime,
                    "trend_strength": self.state["last_market_diagnosis"].trend_strength,
                    "cross_asset_alignment": self.state["last_market_diagnosis"].cross_asset_alignment,
                    "session": self.state["last_market_diagnosis"].session,
                }
                if self.state["last_market_diagnosis"] else None
            ),
            "last_system_diagnosis": (
                {
                    "system_alert": self.state["last_system_diagnosis"].system_alert.value,
                    "risk_multiplier": self.state["last_system_diagnosis"].risk_multiplier,
                    "win_rate_24h": self.state["last_system_diagnosis"].win_rate_24h,
                    "drawdown": self.state["last_system_diagnosis"].drawdown,
                    "consecutive_losses": self.state["last_system_diagnosis"].consecutive_losses,
                    "latency_ms": self.state["last_system_diagnosis"].latency_ms,
                    "brain_confidence": self.state["last_system_diagnosis"].brain_confidence,
                }
                if self.state["last_system_diagnosis"] else None
            ),
            "last_utility_decision": (
                {
                    "utility_score": self.state["last_utility_decision"].utility_score,
                    "threshold": self.state["last_utility_decision"].threshold,
                    "should_trade": self.state["last_utility_decision"].should_trade,
                    "adjusted_confidence": self.state["last_utility_decision"].adjusted_confidence,
                    "adjusted_risk_pct": self.state["last_utility_decision"].adjusted_risk_pct,
                    "adjusted_sl_atr": self.state["last_utility_decision"].adjusted_sl_atr,
                    "adjusted_tp_atr": self.state["last_utility_decision"].adjusted_tp_atr,
                    "reason": self.state["last_utility_decision"].reason,
                }
                if self.state["last_utility_decision"] else None
            ),
        }

        try:
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, "w") as f:
                json.dump(state_data, f, indent=2, default=str)
            logger.info(f"💾 Meta-Brain state saved: {filepath}")
        except Exception as e:
            logger.warning(f"⚠️ Error saving Meta-Brain state: {e}")

        return filepath

    def load_state(self, filepath: Optional[str] = None) -> bool:
        """
        Carga el estado del Meta-Brain desde un archivo JSON.

        Args:
            filepath: Ruta del archivo (opcional, por defecto data/meta_brain_state.json)

        Returns:
            bool: True si se cargó correctamente
        """
        if filepath is None:
            filepath = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "data", "meta_brain_state.json"
            )

        if not os.path.exists(filepath):
            logger.warning(f"⚠️ No state file found: {filepath}")
            return False

        try:
            with open(filepath, "r") as f:
                state_data = json.load(f)

            # Restaurar configuración
            if "config" in state_data:
                self.config.update(state_data["config"])

            # Restaurar estado interno
            if "state" in state_data:
                for key, value in state_data["state"].items():
                    if key in self.state:
                        self.state[key] = value

            # Restaurar calibración
            if "calibration" in state_data:
                for key, value in state_data["calibration"].items():
                    if key in self._calibration:
                        self._calibration[key].update(value)

            # Restaurar caché del sistema
            if "cached_system" in state_data:
                cs = state_data["cached_system"]
                self._cached_win_rate = cs.get("win_rate_24h", 0.5)
                self._cached_drawdown = cs.get("drawdown", 0.0)
                self._cached_consecutive_losses = cs.get("consecutive_losses", 0)
                self._cached_latency = cs.get("latency_ms", 0.0)
                self._cached_brain_confidence = cs.get("brain_confidence", 0.5)

            logger.info(f"📂 Meta-Brain state loaded: {filepath}")
            return True

        except Exception as e:
            logger.warning(f"⚠️ Error loading Meta-Brain state: {e}")
            return False

    def evaluate_signal(
        self,
        probability: float,
        expected_reward_ratio: float,
        atr_current: float,
        atr_median: float,
        volume_delta: float = 0.0,
        momentum_3h: float = 0.0,
        momentum_6h: float = 0.0,
        divergence: float = 0.0,
        hour_utc: Optional[int] = None,
    ) -> UtilityDecision:
        """
        Wrapper simplificado de evaluate() para integración rápida.

        Usa los valores cacheados del sistema (update_system_state)
        y defaults para parámetros opcionales del mercado.

        Args:
            probability: Probabilidad de la señal (0-1)
            expected_reward_ratio: Ratio reward/risk (TP/SL)
            atr_current: ATR actual
            atr_median: ATR mediano histórico
            volume_delta: Volume delta (-1 a 1)
            momentum_3h: Momentum 3h
            momentum_6h: Momentum 6h
            divergence: Divergencia cross-asset
            hour_utc: Hora UTC (auto si None)

        Returns:
            UtilityDecision con la decisión final
        """
        return self.evaluate(
            probability=probability,
            expected_reward_ratio=expected_reward_ratio,
            atr_current=atr_current,
            atr_median=atr_median,
            volume_delta=volume_delta,
            momentum_3h=momentum_3h,
            momentum_6h=momentum_6h,
            divergence=divergence,
            hour_utc=hour_utc,
            win_rate_24h=getattr(self, "_cached_win_rate", 0.5),
            drawdown=getattr(self, "_cached_drawdown", 0.0),
            consecutive_losses=getattr(self, "_cached_consecutive_losses", 0),
            latency_ms=getattr(self, "_cached_latency", 0.0),
            brain_confidence=getattr(self, "_cached_brain_confidence", 0.5),
        )


# ══════════════════════════════════════════════
# DEMO / TEST
# ══════════════════════════════════════════════

def run_demo():
    """
    Demostración del Meta-Brain V10 con escenarios simulados.
    Incluye 4 escenarios: GOLDEN_STATE, TOXICO, FAVORABLE, HIBERNATION.
    """
    import time

    print("\n" + "=" * 70)
    print("🧠 META-BRAIN V10 — DEMO DE TRES CAPAS + HIBERNATION")
    print("=" * 70)
    print("   Métrica maestra: UTILITY (confianza es SOLO visual)")
    print("=" * 70)

    # Inicializar Meta-Brain
    brain = MetaBrainV10()

    # ─── Escenario 1: GOLDEN STATE ───
    print("\n" + "-" * 70)
    print("ESCENARIO 1: GOLDEN STATE — Mercado perfecto, sistema saludable")
    print("-" * 70)

    decision = brain.evaluate(
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

    print(f"   Decisión: {'✅ TRADE' if decision.should_trade else '❌ NO TRADE'}")
    print(f"   Utility: {decision.utility_score:.4f} (threshold: {decision.threshold:.4f}) — MÉTRICA MAESTRA")
    print(f"   Confianza: {decision.adjusted_confidence:.2f} — SOLO VISUAL")
    print(f"   Riesgo: {decision.adjusted_risk_pct*100:.2f}%")
    print(f"   SL: {decision.adjusted_sl_atr:.1f} ATR | TP: {decision.adjusted_tp_atr:.1f} ATR")

    # ─── Escenario 2: TOXICO + SISTEMA ESTRESADO ───
    print("\n" + "-" * 70)
    print("ESCENARIO 2: TOXICO — Mercado volátil, sistema en drawdown")
    print("-" * 70)

    decision2 = brain.evaluate(
        probability=0.58,
        expected_reward_ratio=1.8,
        atr_current=0.0035,
        atr_median=0.0010,
        volume_delta=0.15,
        momentum_3h=0.08,
        momentum_6h=0.12,
        divergence=0.0035,
        hour_utc=19,
        win_rate_24h=0.32,
        drawdown=0.12,
        consecutive_losses=4,
        latency_ms=650,
        brain_confidence=0.35,
    )

    print(f"   Decisión: {'✅ TRADE' if decision2.should_trade else '❌ NO TRADE'}")
    print(f"   Utility: {decision2.utility_score:.4f} (threshold: {decision2.threshold:.4f}) — MÉTRICA MAESTRA")
    print(f"   Confianza: {decision2.adjusted_confidence:.2f} — SOLO VISUAL")
    print(f"   Riesgo: {decision2.adjusted_risk_pct*100:.2f}%")
    print(f"   SL: {decision2.adjusted_sl_atr:.1f} ATR | TP: {decision2.adjusted_tp_atr:.1f} ATR")

    # ─── Escenario 3: FAVORABLE + SISTEMA NORMAL ───
    print("\n" + "-" * 70)
    print("ESCENARIO 3: FAVORABLE — Mercado bueno, sistema normal")
    print("-" * 70)

    decision3 = brain.evaluate(
        probability=0.65,
        expected_reward_ratio=2.0,
        atr_current=0.0015,
        atr_median=0.0012,
        volume_delta=0.45,
        momentum_3h=0.35,
        momentum_6h=0.40,
        divergence=0.0008,
        hour_utc=10,
        win_rate_24h=0.55,
        drawdown=0.03,
        consecutive_losses=1,
        latency_ms=120,
        brain_confidence=0.65,
    )

    print(f"   Decisión: {'✅ TRADE' if decision3.should_trade else '❌ NO TRADE'}")
    print(f"   Utility: {decision3.utility_score:.4f} (threshold: {decision3.threshold:.4f}) — MÉTRICA MAESTRA")
    print(f"   Confianza: {decision3.adjusted_confidence:.2f} — SOLO VISUAL")
    print(f"   Riesgo: {decision3.adjusted_risk_pct*100:.2f}%")
    print(f"   SL: {decision3.adjusted_sl_atr:.1f} ATR | TP: {decision3.adjusted_tp_atr:.1f} ATR")

    # ─── Escenario 4: HIBERNATION ───
    print("\n" + "-" * 70)
    print("ESCENARIO 4: HIBERNATION 🧊 — Sistema en modo supervivencia")
    print("-" * 70)

    decision4 = brain.evaluate(
        probability=0.68,
        expected_reward_ratio=2.2,
        atr_current=0.0018,
        atr_median=0.0012,
        volume_delta=0.50,
        momentum_3h=0.40,
        momentum_6h=0.45,
        divergence=0.0010,
        hour_utc=14,
        win_rate_24h=0.28,
        drawdown=0.18,          # 18% > 15% → HIBERNATION
        consecutive_losses=7,   # 7 >= 6 → HIBERNATION
        latency_ms=1200,        # 1200ms > 1000ms → HIBERNATION
        brain_confidence=0.25,
    )

    print(f"   Decisión: {'✅ TRADE' if decision4.should_trade else '❌ NO TRADE'}")
    print(f"   Utility: {decision4.utility_score:.4f} (threshold: {decision4.threshold:.4f}) — MÉTRICA MAESTRA")
    print(f"   Confianza: {decision4.adjusted_confidence:.2f} — SOLO VISUAL")
    print(f"   Riesgo: {decision4.adjusted_risk_pct*100:.2f}%")
    print(f"   SL: {decision4.adjusted_sl_atr:.1f} ATR | TP: {decision4.adjusted_tp_atr:.1f} ATR")
    print(f"   Razón: {decision4.reason}")

    # ─── Resumen ───
    print(brain.summary())

    return brain


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    )
    run_demo()

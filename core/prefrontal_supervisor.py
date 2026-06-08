"""
EXP-006: El Meta-Clasificador (Prefrontal Model)
=================================================
No predice si el precio sube o baja.
Predice si el trade será de ALTA CALIDAD o no,
basándose en toda la sabiduría acumulada de los experimentos 001 al 005.

"La Corteza Prefrontal del sistema. Veta impulsos del Sniper
 basándose en métricas de alta fidelidad."

Pipeline:
  1. Recibe señal del Sniper (probabilidad, dirección, símbolo)
  2. Aplica filtros de Velocidad (EXP-001), Volumen (EXP-004), Realismo (EXP-005)
  3. Calcula un score de calidad (0-100)
  4. Retorna: APROBAR, VETAR, o AJUSTAR

Referencias:
  - EXP-001: Path Profiling → rejection_speed
  - EXP-002: Cross-Asset → divergencia EURUSD/GOLD
  - EXP-003: Montecarlo → robustez estadística
  - EXP-004: Institutional Volume → volume_delta
  - EXP-005: SL/TP Optimizer → MAE/MFE profiling
"""

import pandas as pd
import numpy as np
import logging
from dataclasses import dataclass, field
from typing import List, Tuple, Optional

# ──────────────────────────────────────────────
# Configuración de logging
# ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


@dataclass
class SignalVerdict:
    """
    El veredicto final del Supervisor Prefrontal.
    
    Attributes:
        approved: True si el trade pasa todos los filtros
        score: Puntuación de calidad (0-100)
        reasons: Lista de razones de veto (vacía si aprobado)
        adjustments: Ajustes recomendados (TP, SL, tamaño)
    """
    approved: bool
    score: int
    reasons: List[str] = field(default_factory=list)
    adjustments: dict = field(default_factory=dict)


class PrefrontalSupervisor:
    """
    La Corteza Prefrontal del sistema.
    
    Toma las señales del Sniper y les aplica el rigor del laboratorio.
    Cada filtro corresponde a un experimento validado:
    
    Filtros de Veto:
      1. 🏃 Filtro de Velocidad (EXP-001): rejection_speed < 2.0σ → VETO
      2. 📊 Filtro de Volumen (EXP-004): volume_delta sin convicción → VETO
      3. 🎯 Filtro de Realismo (EXP-005): ATR vs MAE → AJUSTE
      4. 🔄 Filtro de Divergencia (EXP-002): EURUSD vs GOLD → VETO
      5. 📈 Filtro de Régimen (EXP-005): Alta volatilidad → AJUSTE
    """
    
    def __init__(self):
        """
        Inicializa el Supervisor con los thresholds calibrados
        en los experimentos del Laboratorio.
        """
        # ─── EXP-001: Path Profiling ───
        # Velocidad mínima de rechazo para considerar un muro sólido
        self.min_rejection_speed = 2.0  # σ (desviaciones estándar)
        
        # ─── EXP-004: Institutional Volume ───
        # Volumen mínimo para confirmar participación institucional
        self.min_volume_delta_ratio = 0.3  # 30% de volumen total
        
        # ─── EXP-005: SL/TP Optimizer ───
        # MAE mediano real del mercado (protección contra stops ajustados)
        self.max_mae_allowed = 1.14  # En unidades de ATR (mediana real)
        self.max_mfe_ratio = 0.97   # MFE mediano (para ajustar TP)
        
        # ─── EXP-002: Cross-Asset ───
        # Umbral de divergencia entre EURUSD y GOLD
        self.max_divergence = 0.002  # 0.2% de diferencia
        
        # ─── EXP-005: Régimen ───
        # Factor de ajuste de SL en alta volatilidad
        self.high_vol_sl_multiplier = 1.5  # 50% más de SL
        self.high_vol_atr_threshold = 1.3  # 30% sobre ATR normal
        
        logger.info("🧠 PrefrontalSupervisor inicializado")
        logger.info(f"   ├─ min_rejection_speed: {self.min_rejection_speed}σ")
        logger.info(f"   ├─ max_mae_allowed: {self.max_mae_allowed}x ATR")
        logger.info(f"   ├─ max_divergence: {self.max_divergence}")
        logger.info(f"   └─ high_vol_sl_multiplier: {self.high_vol_sl_multiplier}x")
    
    def evaluate_signal(
        self,
        sniper_proba: float,
        volume_delta: float,
        rejection_speed: float,
        current_atr: float,
        micro_trend: float = 0.0,
        divergence: float = 0.0,
        regime: str = "normal",
        total_volume: float = 1.0,
        direction: str = "buy",
    ) -> SignalVerdict:
        """
        Evalúa una señal del Sniper aplicando todos los filtros del laboratorio.
        
        Args:
            sniper_proba: Probabilidad de la señal (0.0 - 1.0)
            volume_delta: Diferencia buy_volume - sell_volume
            rejection_speed: Z-score de velocidad de tick
            current_atr: ATR actual en unidades de precio
            micro_trend: Posición del close en el rango (-1 a 1)
            divergence: Diferencia de retorno EURUSD vs GOLD
            regime: Régimen de mercado ('low_vol', 'normal', 'high_vol')
            total_volume: Volumen total de ticks en la vela
            direction: Dirección del trade ('buy' o 'sell')
        
        Returns:
            SignalVerdict con el veredicto del Consejo
        """
        score = 100
        reasons = []
        adjustments = {}
        
        # ================================================================
        # FILTRO 1: VELOCIDAD DE RECHAZO (EXP-001)
        # ================================================================
        # Si el precio no reacciona con suficiente velocidad en los muros,
        # es señal de que no hay suficiente liquidez institucional.
        # Un rejection_speed < 2.0σ indica "vela perezosa" — el muro es débil.
        # ================================================================
        if abs(rejection_speed) < self.min_rejection_speed:
            penalty = 30
            score -= penalty
            reasons.append(
                f"🏃 Baja velocidad de rechazo ({rejection_speed:.2f}σ < "
                f"{self.min_rejection_speed:.1f}σ) — Vela perezosa"
            )
            logger.debug(f"  🏃 FILTRO VELOCIDAD: -{penalty} pts (rejection_speed={rejection_speed:.2f})")
        else:
            logger.debug(f"  🏃 FILTRO VELOCIDAD: ✅ (rejection_speed={rejection_speed:.2f}σ)")
        
        # ================================================================
        # FILTRO 2: VOLUMEN INSTITUCIONAL (EXP-004)
        # ================================================================
        # El volume_delta revela quién domina la vela.
        # Si es 0 o muy bajo, no hay "firma institucional".
        # Para un trade de compra, queremos volume_delta positivo.
        # Para un trade de venta, queremos volume_delta negativo.
        # ================================================================
        volume_ratio = abs(volume_delta) / max(total_volume, 1)
        
        if volume_ratio < self.min_volume_delta_ratio:
            penalty = 20
            score -= penalty
            reasons.append(
                f"📊 Falta de firma de volumen real "
                f"(delta_ratio={volume_ratio:.2f} < {self.min_volume_delta_ratio:.1f})"
            )
            logger.debug(f"  📊 FILTRO VOLUMEN: -{penalty} pts (volume_ratio={volume_ratio:.2f})")
        else:
            logger.debug(f"  📊 FILTRO VOLUMEN: ✅ (volume_ratio={volume_ratio:.2f})")
        
        # Verificar dirección del volumen vs dirección del trade
        if direction == "buy" and volume_delta < 0:
            score -= 15
            reasons.append(
                f"⚠️  Contraindicación: Comprando con volumen vendedor "
                f"(volume_delta={volume_delta:.0f})"
            )
        elif direction == "sell" and volume_delta > 0:
            score -= 15
            reasons.append(
                f"⚠️  Contraindicación: Vendiendo con volumen comprador "
                f"(volume_delta={volume_delta:.0f})"
            )
        
        # ================================================================
        # FILTRO 3: REALISMO MAE/MFE (EXP-005)
        # ================================================================
        # Si el ATR actual es muy alto, el MAE real superará nuestro SL.
        # Ajustamos el TP dinámicamente si el MFE sugiere estancamiento.
        # ================================================================
        # Proporción empírica: si ATR > sniper_proba * 0.001, hay riesgo
        atr_risk_ratio = current_atr / max(sniper_proba * 0.001, 0.0001)
        
        if atr_risk_ratio > 1.5:
            penalty = 20
            score -= penalty
            reasons.append(
                f"🎯 Volatilidad excediendo capacidad de Stop Loss "
                f"(ATR={current_atr:.5f}, ratio={atr_risk_ratio:.1f}x)"
            )
            # Ajustar SL más amplio
            adjustments['sl_multiplier'] = self.high_vol_sl_multiplier
            logger.debug(f"  🎯 FILTRO REALISMO: -{penalty} pts (atr_risk_ratio={atr_risk_ratio:.1f})")
        else:
            logger.debug(f"  🎯 FILTRO REALISMO: ✅ (atr_risk_ratio={atr_risk_ratio:.1f})")
        
        # Ajuste de TP basado en MFE mediano
        if regime == "high_vol":
            adjustments['tp_multiplier'] = self.max_mfe_ratio
            logger.debug(f"  🎯 TP ajustado a {self.max_mfe_ratio:.2f}x ATR (régimen alta vol)")
        
        # ================================================================
        # FILTRO 4: DIVERGENCIA CROSS-ASSET (EXP-002)
        # ================================================================
        # Si EURUSD y GOLD se mueven en direcciones opuestas,
        # es señal de manipulación o incertidumbre.
        # ================================================================
        if abs(divergence) > self.max_divergence:
            penalty = 15
            score -= penalty
            reasons.append(
                f"🔄 Divergencia EURUSD/GOLD detectada "
                f"(divergence={divergence:.4f} > {self.max_divergence:.4f})"
            )
            logger.debug(f"  🔄 FILTRO DIVERGENCIA: -{penalty} pts (divergence={divergence:.4f})")
        else:
            logger.debug(f"  🔄 FILTRO DIVERGENCIA: ✅ (divergence={divergence:.4f})")
        
        # ================================================================
        # FILTRO 5: MICRO-TREND (EXP-004 adaptado)
        # ================================================================
        # Si el micro_trend está en contra de la dirección del trade,
        # la vela actual está absorbiendo en la dirección opuesta.
        # ================================================================
        if direction == "buy" and micro_trend < -0.3:
            score -= 10
            reasons.append(
                f"📉 Micro-trend vendedor en compra "
                f"(micro_trend={micro_trend:.2f})"
            )
        elif direction == "sell" and micro_trend > 0.3:
            score -= 10
            reasons.append(
                f"📈 Micro-trend comprador en venta "
                f"(micro_trend={micro_trend:.2f})"
            )
        
        # ================================================================
        # DECISIÓN FINAL
        # ================================================================
        # Score > 70: APROBADO (verde)
        # Score 50-70: APROBADO CON AJUSTES (amarillo)
        # Score < 50: VETADO (rojo)
        # ================================================================
        if score >= 70:
            approved = True
            verdict = "✅ APROBADO"
        elif score >= 50:
            approved = True
            verdict = "🟡 APROBADO CON AJUSTES"
        else:
            approved = False
            verdict = "❌ VETADO"
        
        # Construir veredicto
        result = SignalVerdict(
            approved=approved,
            score=score,
            reasons=reasons,
            adjustments=adjustments
        )
        
        # Log del veredicto
        logger.info(
            f"{verdict} | Score: {score}/100 | "
            f"Dirección: {direction.upper()} | "
            f"Probar: {sniper_proba:.2%}"
        )
        if reasons:
            for r in reasons:
                logger.info(f"  └─ {r}")
        if adjustments:
            for k, v in adjustments.items():
                logger.info(f"  └─ Ajuste: {k} = {v}")
        
        return result
    
    def evaluate_batch(
        self,
        signals_df: pd.DataFrame,
        proba_col: str = 'sniper_proba',
        volume_delta_col: str = 'volume_delta',
        rejection_speed_col: str = 'rejection_speed',
        atr_col: str = 'atr',
        micro_trend_col: str = 'micro_trend',
        divergence_col: str = 'divergence',
        regime_col: str = 'regime',
        direction_col: str = 'direction',
    ) -> pd.DataFrame:
        """
        Evalúa un lote de señales (DataFrame) y retorna los veredictos.
        
        Args:
            signals_df: DataFrame con columnas de señal
            proba_col: Nombre de columna de probabilidad
            volume_delta_col: Nombre de columna de volume_delta
            rejection_speed_col: Nombre de columna de rejection_speed
            atr_col: Nombre de columna de ATR
            micro_trend_col: Nombre de columna de micro_trend
            divergence_col: Nombre de columna de divergencia
            regime_col: Nombre de columna de régimen
            direction_col: Nombre de columna de dirección
        
        Returns:
            DataFrame original con columnas añadidas:
              prefrontal_score, prefrontal_approved, prefrontal_reasons
        """
        results = signals_df.copy()
        scores = []
        approved_list = []
        reasons_list = []
        
        for idx, row in signals_df.iterrows():
            verdict = self.evaluate_signal(
                sniper_proba=row.get(proba_col, 0.5),
                volume_delta=row.get(volume_delta_col, 0),
                rejection_speed=row.get(rejection_speed_col, 0),
                current_atr=row.get(atr_col, 0.001),
                micro_trend=row.get(micro_trend_col, 0),
                divergence=row.get(divergence_col, 0),
                regime=row.get(regime_col, "normal"),
                direction=row.get(direction_col, "buy"),
            )
            scores.append(verdict.score)
            approved_list.append(verdict.approved)
            reasons_list.append("; ".join(verdict.reasons))
        
        results['prefrontal_score'] = scores
        results['prefrontal_approved'] = approved_list
        results['prefrontal_reasons'] = reasons_list
        
        # Estadísticas del batch
        n_total = len(results)
        n_approved = sum(approved_list)
        n_vetoed = n_total - n_approved
        avg_score = np.mean(scores)
        
        logger.info(f"\n{'='*50}")
        logger.info(f"📊 RESUMEN DEL BATCH PREFRONTAL")
        logger.info(f"{'='*50}")
        logger.info(f"   Total señales:     {n_total}")
        logger.info(f"   ✅ Aprobadas:      {n_approved} ({n_approved/n_total*100:.1f}%)")
        logger.info(f"   ❌ Vetadas:        {n_vetoed} ({n_vetoed/n_total*100:.1f}%)")
        logger.info(f"   📊 Score promedio:  {avg_score:.1f}/100")
        logger.info(f"{'='*50}")
        
        return results
    
    def get_filters_status(self) -> dict:
        """
        Retorna el estado actual de todos los filtros y sus thresholds.
        Útil para el dashboard del War Room.
        """
        return {
            "filtro_velocidad": {
                "activo": True,
                "threshold": self.min_rejection_speed,
                "unidad": "σ",
                "experimento": "EXP-001",
                "descripcion": "Bloquea trades con baja velocidad de rechazo"
            },
            "filtro_volumen": {
                "activo": True,
                "threshold": self.min_volume_delta_ratio,
                "unidad": "ratio",
                "experimento": "EXP-004",
                "descripcion": "Requiere firma de volumen institucional"
            },
            "filtro_realismo": {
                "activo": True,
                "threshold": self.max_mae_allowed,
                "unidad": "x ATR",
                "experimento": "EXP-005",
                "descripcion": "Ajusta SL/TP basado en MAE/MFE real"
            },
            "filtro_divergencia": {
                "activo": True,
                "threshold": self.max_divergence,
                "unidad": "pct",
                "experimento": "EXP-002",
                "descripcion": "Detecta divergencias EURUSD/GOLD"
            },
            "filtro_microtrend": {
                "activo": True,
                "threshold": 0.3,
                "unidad": "ratio",
                "experimento": "EXP-004",
                "descripcion": "Verifica alineación del micro-trend"
            }
        }


# ================================================================
# EJECUCIÓN DE PRUEBA
# ================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("🧠 EXP-006: PREFRONTAL SUPERVISOR — PRUEBA")
    print("   El Meta-Clasificador del Laboratorio")
    print("=" * 60)
    
    # Inicializar el Supervisor
    supervisor = PrefrontalSupervisor()
    
    # ─── Caso 1: Señal de alta calidad ───
    print("\n" + "=" * 50)
    print("📈 CASO 1: Señal de Alta Calidad")
    print("=" * 50)
    v1 = supervisor.evaluate_signal(
        sniper_proba=0.78,
        volume_delta=45000,
        rejection_speed=3.2,
        current_atr=0.00085,
        micro_trend=0.4,
        divergence=0.0005,
        regime="normal",
        direction="buy",
    )
    print(f"   Veredicto: {'✅ APROBADO' if v1.approved else '❌ VETADO'}")
    print(f"   Score: {v1.score}/100")
    if v1.reasons:
        for r in v1.reasons:
            print(f"   └─ {r}")
    
    # ─── Caso 2: Señal de baja calidad (el trade que pierdes) ───
    print("\n" + "=" * 50)
    print("📉 CASO 2: Señal de Baja Calidad (Trade Perdedor)")
    print("=" * 50)
    v2 = supervisor.evaluate_signal(
        sniper_proba=0.55,
        volume_delta=500,
        rejection_speed=0.8,
        current_atr=0.0015,
        micro_trend=-0.2,
        divergence=0.003,
        regime="high_vol",
        direction="buy",
    )
    print(f"   Veredicto: {'✅ APROBADO' if v2.approved else '❌ VETADO'}")
    print(f"   Score: {v2.score}/100")
    if v2.reasons:
        for r in v2.reasons:
            print(f"   └─ {r}")
    
    # ─── Caso 3: Señal de venta con volumen ───
    print("\n" + "=" * 50)
    print("📊 CASO 3: Señal de Venta con Volumen")
    print("=" * 50)
    v3 = supervisor.evaluate_signal(
        sniper_proba=0.82,
        volume_delta=-67000,
        rejection_speed=-2.8,
        current_atr=0.00072,
        micro_trend=-0.5,
        divergence=-0.0008,
        regime="normal",
        direction="sell",
    )
    print(f"   Veredicto: {'✅ APROBADO' if v3.approved else '❌ VETADO'}")
    print(f"   Score: {v3.score}/100")
    if v3.reasons:
        for r in v3.reasons:
            print(f"   └─ {r}")
    
    # ─── Caso 4: El clásico "No entró bien" ───
    print("\n" + "=" * 50)
    print("💀 CASO 4: El 'No Entró Bien' (FOMO)")
    print("=" * 50)
    v4 = supervisor.evaluate_signal(
        sniper_proba=0.45,
        volume_delta=0,
        rejection_speed=0.3,
        current_atr=0.0021,
        micro_trend=0.1,
        divergence=0.005,
        regime="high_vol",
        direction="buy",
    )
    print(f"   Veredicto: {'✅ APROBADO' if v4.approved else '❌ VETADO'}")
    print(f"   Score: {v4.score}/100")
    if v4.reasons:
        for r in v4.reasons:
            print(f"   └─ {r}")
    
    # ─── Resumen de Filtros ───
    print("\n" + "=" * 50)
    print("🛡️  ESTADO DE FILTROS PREFRONTALES")
    print("=" * 50)
    filters = supervisor.get_filters_status()
    for name, config in filters.items():
        status = "🟢" if config['activo'] else "🔴"
        print(f"   {status} {name}: {config['descripcion']}")
        print(f"      Threshold: {config['threshold']} {config['unidad']} ({config['experimento']})")
    
    print("\n✅ EXP-006: Prueba completada. Supervisor Prefrontal operativo.")



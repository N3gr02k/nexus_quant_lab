"""
NEXUS QUANT LAB — V8.2 Sentinel Council (Multi-Pillar Check)
=============================================================
sentinel_council.py

EL CONSEJO DE CENTINELAS V8.2 — Lógica Diferenciada por Activo.

Ahora el Consejo trata al Euro y al Oro de forma distinta basándose
en los hallazgos del EXP-013 (Whale Tracker):

  EURUSD:  Ballena detectada -> 🔴 VETO (Firma de Re-acumulacion, WR 7.69%)
  GOLD:    Ballena detectada -> 🟢 BOOST (Firma de Climax "The Vacuum", WR 85.71%)

Pipeline V8.2:
  1. Recibir orden propuesta por el Sniper
  2. Aplicar los 5 vetos clasicos (HORA, VELOCIDAD, VOLUMEN, REGIMEN, CONFIANZA)
  3. CAPA 6 — WHALE SENTINEL (EXP-013):
     - Detectar presencia de ballena con thresholds calibrados por activo
     - EURUSD: VETO si ballena presente (ruido tecnico)
     - GOLD: BOOST de confianza si ballena presente (The Vacuum)
  4. Emitir veredicto: APROBADO / VETADO / APROBADO CON BOOST

Integracion con produccion:
  from models.sentinel_council import SentinelCouncilV2
  council = SentinelCouncilV2()
  verdict = council.verify_order("GOLD", 0.85, 2.1, 0.15, "NEUTRO")

Dependencias:
  pip install pandas numpy

Autor: Nexus Quant Lab
Fecha: 2026-06-01 (V8.2 — Multi-Pillar Check)
"""

import numpy as np
import logging
import os
import json
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict

# ──────────────────────────────────────────────
# Configuracion
# ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


@dataclass
class CouncilVerdict:
    """
    Veredicto completo del Consejo de Centinelas.

    Attributes:
        approved: Si la orden pasa todos los vetos
        reason: Razon del veto o confirmacion de aprobacion
        veto_layer: Que capa del Consejo activo el veto (si aplica)
        boost: Si la senal recibio un boost de confianza (Whale GOLD)
        boost_amount: Cuanto se incremento la confianza
        details: Detalles adicionales del analisis
    """
    approved: bool
    reason: str
    veto_layer: str = ""
    boost: bool = False
    boost_amount: float = 0.0
    details: Dict = field(default_factory=dict)


class SentinelCouncilV2:
    """
    El Consejo de Centinelas V8.2 — Logica Diferenciada por Activo.

    Integra el conocimiento de 13 experimentos en 6 capas de veto:
      - EXP-001: Path Profiling (velocidad de rechazo)
      - EXP-002: Cross-Asset (divergencia Euro/Oro)
      - EXP-003: Montecarlo (gestion de riesgo sistemico)
      - EXP-004: Volume Delta (volumen institucional)
      - EXP-005: Adverse Excursion (MAE/MFE profiling)
      - EXP-006: Prefrontal Supervisor (meta-clasificador)
      - EXP-007: Error Brain (feedback loop)
      - EXP-008: News Shield (horas de fixing)
      - EXP-009: Alpha Stacker (factores alfa)
      - EXP-010: Shadow Clustering (personalidades del mercado)
      - EXP-011: Regime-Aware Sniper (cambio de estrategia por regimen)
      - EXP-013: Whale Tracker (deteccion de ballenas)
      - EXP-013-GOLD: Whale Tracker Gold (Firma de Climax)
    """

    def __init__(self, config: Optional[dict] = None):
        """
        Inicializa el Consejo de Centinelas V8.2.

        Args:
            config: Diccionario opcional para sobrescribir parametros
        """
        # ─── Configuracion por defecto ───
        self.config = {
            # EXP-008: News Shield — Hora de fixing
            "forbidden_hour_utc": 19,
            "forbidden_hour_window": 1,
            "forbidden_hour_penalty": "Zona de Muerte (Fixing Time 19:00 UTC)",

            # EXP-001: Path Profiling — Velocidad de rechazo (Modo Ataque: 0.5)
            "min_rejection_speed": 0.5,
            "speed_penalty": "Falta de explosividad (Vela perezosa)",

            # EXP-004: Volume Delta — Volumen institucional
            "min_volume_alignment": 0.01,
            "volume_penalty": "Volumen Institucional en contra",

            # EXP-010/011: Shadow Clustering — Regimen (Modo Explorador: vacío)
            "forbidden_regimes": [],
            "regime_penalty": "Regimen de Manipulacion Activa",

            # EXP-003: Montecarlo — Limites de riesgo
            "max_consecutive_losses": 3,
            "daily_loss_limit": 0.05,

            # Umbrales generales
            "min_confidence": 0.75,

            # ─── EXP-013: Whale Tracker — Configuracion por Activo ───
            "whale_config": {
                "EURUSD": {
                    "vol_std": 1.5,
                    "speed": 2.0,
                    "abs_z": 1.0,
                    "action": "VETO",
                    "description": "Firma de Re-acumulacion (WR 7.69%)",
                },
                "GOLD": {
                    "vol_std": 1.2,
                    "speed": 1.5,
                    "abs_z": 0.8,
                    "action": "BOOST",
                    "description": "Firma de Climax 'The Vacuum' (WR 85.71%)",
                },
            },

            # Boost de confianza para GOLD cuando hay ballena
            "gold_boost_amount": 0.15,  # Incremento de confianza
            "gold_boost_max_confidence": 0.95,  # Confianza maxima tras boost
        }

        # Sobrescribir con configuracion personalizada
        if config:
            self.config.update(config)

        # Estado del Consejo
        self.state = {
            "consecutive_losses": 0,
            "daily_pnl": 0.0,
            "total_vetoed": 0,
            "total_approved": 0,
            "total_boosted": 0,
            "last_verdict": None,
            "veto_history": [],
        }

        # Cargar metricas de ballena desde archivos JSON si existen
        self.whale_metrics = self._load_whale_metrics()

        logger.info("🛡️ SentinelCouncilV2 inicializado")
        logger.info(f"   ⚙️  Configuracion: {json.dumps(self.config, indent=2)}")

    def _load_whale_metrics(self) -> Dict:
        """Carga metricas de ballena desde archivos JSON."""
        metrics = {}
        whale_files = {
            "EURUSD": "data/eurusd_whale_metrics.json",
            "GOLD": "data/gold_whale_metrics_calibrated.json",
        }
        for symbol, path in whale_files.items():
            if os.path.exists(path):
                try:
                    with open(path, "r") as f:
                        metrics[symbol] = json.load(f)
                    logger.info(f"   🐋 Metricas Whale {symbol} cargadas: {metrics[symbol].get('total_signals', 0)} senales")
                except Exception as e:
                    logger.warning(f"   ⚠️ No se pudieron cargar metricas Whale {symbol}: {e}")
        return metrics

    def _check_whale_presence(
        self,
        symbol: str,
        tick_vol_std: float,
        rejection_speed: float,
        absorption_z: float,
    ) -> Tuple[bool, str]:
        """
        Verifica si hay presencia de ballena segun thresholds calibrados por activo.

        Args:
            symbol: Simbolo del activo
            tick_vol_std: Desviacion estandar del volumen de ticks
            rejection_speed: Velocidad de rechazo en sigma
            absorption_z: Z-score de absorcion

        Returns:
            Tuple[bool, str]: (ballena_detectada, descripcion)
        """
        cfg = self.config["whale_config"].get(symbol)
        if cfg is None:
            return False, ""

        # Verificar thresholds
        vol_ok = tick_vol_std >= cfg["vol_std"]
        speed_ok = abs(rejection_speed) >= cfg["speed"]
        abs_ok = absorption_z >= cfg["abs_z"]

        if vol_ok and speed_ok and abs_ok:
            return True, cfg["description"]

        return False, ""

    def verify_order(
        self,
        symbol: str,
        proba: float,
        rejection_speed: float,
        volume_delta: float,
        regime: str,
        direction: str = "LONG",
        current_hour_utc: Optional[int] = None,
        tick_vol_std: float = 0.0,
        absorption_z: float = 0.0,
    ) -> CouncilVerdict:
        """
        Evalua una orden propuesta contra todos los vetos del Consejo V8.2.

        Args:
            symbol: Simbolo del activo (EURUSD, GOLD, GBPUSD)
            proba: Probabilidad de la senal del Sniper (0-1)
            rejection_speed: Velocidad de rechazo en desviaciones estandar
            volume_delta: Volume delta normalizado (-1 a 1)
            regime: Regimen del mercado detectado
            direction: Direccion del trade ("LONG" o "SHORT")
            current_hour_utc: Hora UTC actual (auto-detectada si no se provee)
            tick_vol_std: Desviacion estandar del volumen de ticks (para Whale)
            absorption_z: Z-score de absorcion (para Whale)

        Returns:
            CouncilVerdict con el resultado de la evaluacion
        """
        # Auto-detectar hora UTC si no se provee
        if current_hour_utc is None:
            current_hour_utc = datetime.now(timezone.utc).hour

        details = {
            "symbol": symbol,
            "proba": proba,
            "rejection_speed": rejection_speed,
            "volume_delta": volume_delta,
            "regime": regime,
            "direction": direction,
            "hour_utc": current_hour_utc,
            "tick_vol_std": tick_vol_std,
            "absorption_z": absorption_z,
        }

        # ──────────────────────────────────────────────
        # CAPA 1: VETO DE HORA (EXP-008)
        # ──────────────────────────────────────────────
        forbidden_start = self.config["forbidden_hour_utc"] - self.config["forbidden_hour_window"]
        forbidden_end = self.config["forbidden_hour_utc"] + self.config["forbidden_hour_window"]

        if forbidden_start <= current_hour_utc <= forbidden_end:
            self.state["total_vetoed"] += 1
            self.state["last_verdict"] = "VETO_HORA"
            self.state["veto_history"].append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "layer": "HORA",
                "reason": self.config["forbidden_hour_penalty"],
                "details": details,
            })

            return CouncilVerdict(
                approved=False,
                reason=f"🛡️ VETO: {self.config['forbidden_hour_penalty']}",
                veto_layer="HORA (EXP-008)",
                details=details,
            )

        # ──────────────────────────────────────────────
        # CAPA 2: VETO DE VELOCIDAD (EXP-001)
        # ──────────────────────────────────────────────
        if abs(rejection_speed) < self.config["min_rejection_speed"]:
            self.state["total_vetoed"] += 1
            self.state["last_verdict"] = "VETO_VELOCIDAD"
            self.state["veto_history"].append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "layer": "VELOCIDAD",
                "reason": self.config["speed_penalty"],
                "details": details,
            })

            return CouncilVerdict(
                approved=False,
                reason=(
                    f"🛡️ VETO: {self.config['speed_penalty']} "
                    f"(|rejection_speed|={abs(rejection_speed):.2f}sigma < "
                    f"{self.config['min_rejection_speed']:.1f}sigma)"
                ),
                veto_layer="VELOCIDAD (EXP-001)",
                details=details,
            )

        # ──────────────────────────────────────────────
        # CAPA 3: VETO DE VOLUMEN (EXP-004)
        # ──────────────────────────────────────────────
        if proba > self.config["min_confidence"]:
            if direction == "LONG" and volume_delta < -self.config["min_volume_alignment"]:
                self.state["total_vetoed"] += 1
                self.state["last_verdict"] = "VETO_VOLUMEN"
                self.state["veto_history"].append({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "layer": "VOLUMEN",
                    "reason": self.config["volume_penalty"],
                    "details": details,
                })

                return CouncilVerdict(
                    approved=False,
                    reason=(
                        f"🛡️ VETO: {self.config['volume_penalty']} "
                        f"(volume_delta={volume_delta:.2f} en contra de LONG)"
                    ),
                    veto_layer="VOLUMEN (EXP-004)",
                    details=details,
                )

            elif direction == "SHORT" and volume_delta > self.config["min_volume_alignment"]:
                self.state["total_vetoed"] += 1
                self.state["last_verdict"] = "VETO_VOLUMEN"
                self.state["veto_history"].append({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "layer": "VOLUMEN",
                    "reason": self.config["volume_penalty"],
                    "details": details,
                })

                return CouncilVerdict(
                    approved=False,
                    reason=(
                        f"🛡️ VETO: {self.config['volume_penalty']} "
                        f"(volume_delta={volume_delta:.2f} en contra de SHORT)"
                    ),
                    veto_layer="VOLUMEN (EXP-004)",
                    details=details,
                )

        # ──────────────────────────────────────────────
        # CAPA 4: VETO DE REGIMEN (EXP-010 / EXP-011)
        # ──────────────────────────────────────────────
        regime_upper = regime.upper().strip()
        for forbidden in self.config["forbidden_regimes"]:
            if forbidden in regime_upper:
                self.state["total_vetoed"] += 1
                self.state["last_verdict"] = "VETO_REGIMEN"
                self.state["veto_history"].append({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "layer": "REGIMEN",
                    "reason": self.config["regime_penalty"],
                    "details": details,
                })

                return CouncilVerdict(
                    approved=False,
                    reason=(
                        f"🛡️ VETO: {self.config['regime_penalty']} "
                        f"(Regimen detectado: {regime})"
                    ),
                    veto_layer="REGIMEN (EXP-010/011)",
                    details=details,
                )

        # ──────────────────────────────────────────────
        # CAPA 5: VETO DE CONFIANZA (EXP-003 / EXP-006)
        # ──────────────────────────────────────────────
        if proba < self.config["min_confidence"]:
            self.state["total_vetoed"] += 1
            self.state["last_verdict"] = "VETO_CONFIANZA"
            self.state["veto_history"].append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "layer": "CONFIANZA",
                "reason": "Confianza del Sniper insuficiente",
                "details": details,
            })

            return CouncilVerdict(
                approved=False,
                reason=(
                    f"🛡️ VETO: Confianza del Sniper insuficiente "
                    f"(proba={proba:.2f} < {self.config['min_confidence']:.2f})"
                ),
                veto_layer="CONFIANZA (EXP-006)",
                details=details,
            )

        # ──────────────────────────────────────────────
        # CAPA 6: WHALE SENTINEL (EXP-013) — NUEVO V8.2
        # ──────────────────────────────────────────────
        whale_detected, whale_desc = self._check_whale_presence(
            symbol, tick_vol_std, rejection_speed, absorption_z
        )

        if whale_detected:
            cfg = self.config["whale_config"].get(symbol, {})
            action = cfg.get("action", "IGNORE")

            if action == "VETO":
                # EURUSD: Ballena detectada = VETO
                self.state["total_vetoed"] += 1
                self.state["last_verdict"] = "VETO_WHALE"
                self.state["veto_history"].append({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "layer": "WHALE",
                    "reason": f"Ballena detectada en {symbol}: {whale_desc}",
                    "details": details,
                })

                return CouncilVerdict(
                    approved=False,
                    reason=(
                        f"🛡️ VETO WHALE: Ballena detectada en {symbol}. "
                        f"{whale_desc}. "
                        f"Vol={tick_vol_std:.1f}sigma, Speed={abs(rejection_speed):.1f}sigma, "
                        f"AbsZ={absorption_z:.1f}"
                    ),
                    veto_layer="WHALE (EXP-013)",
                    details=details,
                )

            elif action == "BOOST":
                # GOLD: Ballena detectada = BOOST de confianza
                boost_amount = self.config["gold_boost_amount"]
                boosted_proba = min(
                    proba + boost_amount,
                    self.config["gold_boost_max_confidence"]
                )
                actual_boost = boosted_proba - proba

                self.state["total_boosted"] += 1
                self.state["last_verdict"] = "APROBADO_CON_BOOST"

                logger.info(
                    f"🐋 BOOST WHALE GOLD: Confianza {proba:.2f} -> {boosted_proba:.2f} "
                    f"(+{actual_boost:.2f}) por deteccion de ballena"
                )

                return CouncilVerdict(
                    approved=True,
                    reason=(
                        f"🐋✅ APROBADO CON BOOST WHALE: Ballena detectada en {symbol}. "
                        f"{whale_desc}. Confianza elevada de {proba:.2f} a {boosted_proba:.2f} "
                        f"(+{actual_boost:.2f})"
                    ),
                    veto_layer="",
                    boost=True,
                    boost_amount=actual_boost,
                    details={**details, "boosted_proba": boosted_proba},
                )

        # ──────────────────────────────────────────────
        # ✅ TODOS LOS VETOS PASARON
        # ──────────────────────────────────────────────
        self.state["total_approved"] += 1
        self.state["last_verdict"] = "APROBADO"

        return CouncilVerdict(
            approved=True,
            reason="✅ ORDEN APROBADA POR EL CONSEJO — Todos los centinelas en verde",
            veto_layer="",
            details=details,
        )

    def report_consecutive_loss(self, loss_amount: float) -> Optional[str]:
        """
        Reporta una perdida consecutiva al Consejo.
        Si se excede el limite, el Consejo puede recomendar pausa.

        Args:
            loss_amount: Monto de la perdida en unidades de cuenta

        Returns:
            Advertencia si se excede el limite, None si esta dentro de parametros
        """
        self.state["consecutive_losses"] += 1
        self.state["daily_pnl"] -= abs(loss_amount)

        if self.state["consecutive_losses"] >= self.config["max_consecutive_losses"]:
            return (
                f"⚠️ ALERTA DEL CONSEJO: {self.state['consecutive_losses']} "
                f"perdidas consecutivas. Considere pausar operaciones."
            )

        if abs(self.state["daily_pnl"]) > self.config["daily_loss_limit"] * 10000:
            return (
                f"🚨 ALERTA DEL CONSEJO: Limite diario de perdida alcanzado "
                f"(${abs(self.state['daily_pnl']):.2f}). Deteniendo operaciones."
            )

        return None

    def report_win(self, win_amount: float):
        """Reporta una ganancia al Consejo (resetea contador de perdidas)."""
        self.state["consecutive_losses"] = 0
        self.state["daily_pnl"] += abs(win_amount)

    def reset_daily_state(self):
        """Resetea el estado diario del Consejo."""
        self.state["consecutive_losses"] = 0
        self.state["daily_pnl"] = 0.0
        logger.info("🔄 Estado diario del Consejo resetado")

    def get_semaphore_status(self) -> str:
        """
        Retorna el estado del semaforo del Consejo.

        Returns:
            "VERDE": Todo en orden, listo para operar
            "AMARILLO": Precaución, alguna advertencia activa
            "ROJO": Veto activo, no operar
        """
        if self.state["consecutive_losses"] >= self.config["max_consecutive_losses"]:
            return "ROJO"

        if self.state["consecutive_losses"] >= self.config["max_consecutive_losses"] - 1:
            return "AMARILLO"

        current_hour = datetime.now(timezone.utc).hour
        forbidden_start = self.config["forbidden_hour_utc"] - self.config["forbidden_hour_window"]
        forbidden_end = self.config["forbidden_hour_utc"] + self.config["forbidden_hour_window"]

        if forbidden_start <= current_hour <= forbidden_end:
            return "ROJO"

        return "VERDE"

    def get_veto_summary(self) -> Dict:
        """
        Retorna un resumen de los vetos del Consejo.
        """
        history = self.state["veto_history"]
        total = len(history)

        if total == 0:
            return {
                "total_vetoes": 0,
                "layers": {},
                "last_verdict": self.state["last_verdict"],
            }

        layers = {}
        for entry in history:
            layer = entry["layer"]
            layers[layer] = layers.get(layer, 0) + 1

        return {
            "total_vetoes": total,
            "layers": layers,
            "last_verdict": self.state["last_verdict"],
            "last_veto_reason": history[-1]["reason"] if history else None,
        }

    def summary(self) -> str:
        """Retorna un resumen formateado del estado del Consejo."""
        semaphore = self.get_semaphore_status()
        semaphore_icon = {"VERDE": "🟢", "AMARILLO": "🟡", "ROJO": "🔴"}

        lines = [
            "\n" + "=" * 70,
            "🛡️ CONSEJO DE CENTINELAS V8.2 — RESUMEN",
            "=" * 70,
            f"\n📊 ESTADO DEL SEMAFORO: {semaphore_icon.get(semaphore, '❓')} {semaphore}",
            f"\n📈 ESTADISTICAS:",
            f"   Total aprobados:     {self.state['total_approved']}",
            f"   Total vetados:       {self.state['total_vetoed']}",
            f"   Total boosted:       {self.state['total_boosted']}",
            f"   Rachas de perdidas:  {self.state['consecutive_losses']}",
            f"   P&L Diario:          ${self.state['daily_pnl']:.2f}",
        ]

        veto_summary = self.get_veto_summary()
        if veto_summary["total_vetoes"] > 0:
            lines.append(f"\n📋 PERFIL DE VETOS ({veto_summary['total_vetoes']} totales):")
            for layer, count in veto_summary["layers"].items():
                pct = count / veto_summary["total_vetoes"] * 100
                lines.append(f"   ❌ {layer}: {count} ({pct:.1f}%)")

        # Mostrar configuracion Whale
        lines.append("\n🐋 CONFIGURACION WHALE POR ACTIVO:")
        for sym, cfg in self.config["whale_config"].items():
            lines.append(
                f"   {sym}: Vol>{cfg['vol_std']}sigma, Speed>{cfg['speed']}sigma, "
                f"AbsZ>{cfg['abs_z']} -> {cfg['action']}"
            )

        lines.append("\n" + "=" * 70)
        return "\n".join(lines)


# ──────────────────────────────────────────────
# EJECUCION DE PRUEBA
# ──────────────────────────────────────────────

def run_demo():
    """
    Ejecuta una demostracion del Consejo de Centinelas V8.2
    con casos que simulan ordenes reales del Sniper,
    incluyendo la nueva logica diferenciada Whale.
    """
    print("\n" + "=" * 70)
    print("🛡️ V8.2 DEMO: CONSEJO DE CENTINELAS (MULTI-PILLAR CHECK)")
    print("=" * 70)

    council = SentinelCouncilV2()

    # ─── Caso 1: Orden Aprobada (EURUSD) ───
    print("\n" + "─" * 70)
    print("📈 CASO 1: EURUSD — ORDEN DE ALTA CALIDAD")
    print("   proba=0.92 | speed=3.2sigma | vol=+0.35 | NEUTRO | Sin ballena")
    print("─" * 70)

    v1 = council.verify_order(
        symbol="EURUSD", proba=0.92, rejection_speed=3.2,
        volume_delta=0.35, regime="NEUTRO", direction="LONG",
        current_hour_utc=14,
        tick_vol_std=0.5, absorption_z=0.3,
    )
    print(f"   {v1.reason}")

    # ─── Caso 2: EURUSD con Ballena (VETO) ───
    print("\n" + "─" * 70)
    print("🐋 CASO 2: EURUSD — BALLENA DETECTADA (VETO)")
    print("   proba=0.88 | speed=2.5sigma | vol=+0.15 | NEUTRO | Ballena!")
    print("─" * 70)

    v2 = council.verify_order(
        symbol="EURUSD", proba=0.88, rejection_speed=2.5,
        volume_delta=0.15, regime="NEUTRO", direction="LONG",
        current_hour_utc=14,
        tick_vol_std=2.0, absorption_z=1.5,
    )
    print(f"   {v2.reason}")

    # ─── Caso 3: GOLD con Ballena (BOOST) ───
    print("\n" + "─" * 70)
    print("🐋 CASO 3: GOLD — BALLENA DETECTADA (BOOST)")
    print("   proba=0.78 | speed=2.2sigma | vol=+0.10 | NEUTRO | Ballena!")
    print("─" * 70)

    v3 = council.verify_order(
        symbol="GOLD", proba=0.78, rejection_speed=2.2,
        volume_delta=0.10, regime="NEUTRO", direction="SHORT",
        current_hour_utc=14,
        tick_vol_std=1.5, absorption_z=1.2,
    )
    print(f"   {v3.reason}")
    if v3.boost:
        print(f"   🚀 Boost aplicado: +{v3.boost_amount:.2f} a la confianza")

    # ─── Caso 4: GOLD sin Ballena (Aprobado normal) ───
    print("\n" + "─" * 70)
    print("📈 CASO 4: GOLD — SIN BALLENA (APROBADO NORMAL)")
    print("   proba=0.85 | speed=2.8sigma | vol=+0.25 | NEUTRO | Sin ballena")
    print("─" * 70)

    v4 = council.verify_order(
        symbol="GOLD", proba=0.85, rejection_speed=2.8,
        volume_delta=0.25, regime="NEUTRO", direction="LONG",
        current_hour_utc=14,
        tick_vol_std=0.5, absorption_z=0.3,
    )
    print(f"   {v4.reason}")

    # ─── Caso 5: Veto por Hora ───
    print("\n" + "─" * 70)
    print("🕐 CASO 5: VETO POR HORA (FIXING)")
    print("   EURUSD LONG | proba=0.85 | speed=2.5sigma | vol=+0.15 | NEUTRO")
    print("─" * 70)

    v5 = council.verify_order(
        symbol="EURUSD", proba=0.85, rejection_speed=2.5,
        volume_delta=0.15, regime="NEUTRO", direction="LONG",
        current_hour_utc=19,
    )
    print(f"   {v5.reason}")

    # ─── Caso 6: Veto por Velocidad ───
    print("\n" + "─" * 70)
    print("🐌 CASO 6: VETO POR VELOCIDAD")
    print("   GOLD LONG | proba=0.78 | speed=0.8sigma | vol=+0.10 | NEUTRO")
    print("─" * 70)

    v6 = council.verify_order(
        symbol="GOLD", proba=0.78, rejection_speed=0.8,
        volume_delta=0.10, regime="NEUTRO", direction="LONG",
        current_hour_utc=14,
    )
    print(f"   {v6.reason}")

    # ─── Caso 7: Veto por Regimen ───
    print("\n" + "─" * 70)
    print("🌀 CASO 7: VETO POR REGIMEN (BARRIDO DE LIQUIDEZ)")
    print("   GOLD SHORT | proba=0.88 | speed=3.5sigma | vol=-0.25 | BARRIDO")
    print("─" * 70)

    v7 = council.verify_order(
        symbol="GOLD", proba=0.88, rejection_speed=3.5,
        volume_delta=-0.25, regime="BARRIDO DE LIQUIDEZ", direction="SHORT",
        current_hour_utc=14,
    )
    print(f"   {v7.reason}")

    # ─── Resumen ───
    print("\n" + "=" * 70)
    print("📊 RESUMEN DE LA DEMO V8.2")
    print("=" * 70)

    casos = [
        ("EURUSD Alta Calidad", v1),
        ("EURUSD Ballena (VETO)", v2),
        ("GOLD Ballena (BOOST)", v3),
        ("GOLD Sin Ballena", v4),
        ("Veto Hora (Fixing)", v5),
        ("Veto Velocidad", v6),
        ("Veto Regimen", v7),
    ]

    for nombre, v in casos:
        icono = "✅" if v.approved else "❌"
        boost_icon = " 🐋🚀" if v.boost else ""
        print(f"\n{icono} {nombre}{boost_icon}:")
        print(f"   {v.reason}")
        if v.veto_layer:
            print(f"   Capa: {v.veto_layer}")

    print(f"\n📊 Semaforo actual: {council.get_semaphore_status()}")
    print(council.summary())

    return council


if __name__ == "__main__":
    council = run_demo()

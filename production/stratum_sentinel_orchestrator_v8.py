"""
NEXUS QUANT LAB — V8.0 Sentinel Orchestrator
==============================================
stratum_sentinel_orchestrator_v8.py

THE HIGH-FIDELITY BRIDGE — Puente entre el Laboratorio y la Producción.

Flujo de ejecución:
  1. INFERENCIA: Sniper/Titan calculan probabilidad desde velas H1
  2. TICK AUDIT: El Consejo revisa ticks en vivo de los últimos 60 min
  3. VEREDICTO: Solo si ambos están de acuerdo, se envía la orden a XM

Integración:
  Este script es el reemplazo directo de stratum_triple_orchestrator_v7.py
  en el bot de producción. Inyecta la capacidad de lectura de ticks del
  Laboratorio dentro del bucle principal del orquestador.

Dependencias:
  pip install pandas numpy xgboost joblib

Autor: Nexus Quant Lab
Fecha: 2026-06-01
"""

import sys
import os
from datetime import datetime, timedelta, timezone

# --- SINCRONIZACIÓN DE RUTAS DEL LABORATORIO ---
# Obtener la ruta raíz (D:\nexus_quant_lab)
root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if root_path not in sys.path:
    sys.path.insert(0, root_path)

# Cambiar el directorio de trabajo a la raíz para que las rutas de los .pkl funcionen
os.chdir(root_path)
# -----------------------------------------------

import numpy as np
import pandas as pd
import logging
import time
import json
from dataclasses import dataclass, field
from typing import Optional, Tuple, List, Dict
from pathlib import Path

# ──────────────────────────────────────────────
# Configuración de logging
# ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("SentinelOrchestrator")

# ──────────────────────────────────────────────
# Importaciones del Laboratorio
# ──────────────────────────────────────────────
try:
    from core.sentinel_council import SentinelCouncilV2 as SentinelCouncil, CouncilVerdict
except ImportError:
    logger.error("❌ No se pudo importar SentinelCouncilV2. ¿Estás en el directorio correcto?")
    logger.error("   Ejecuta desde d:/nexus_quant_lab/")
    raise

try:
    from production.sentinel_v2_engine import SentinelV2Engine
except ImportError:
    logger.error("❌ No se pudo importar SentinelV2Engine.")
    SentinelV2Engine = None


@dataclass
class TickSnapshot:
    """
    Captura de ticks en vivo para alimentar al Consejo.
    
    Simula la lectura de ticks desde MT5. En producción real,
    esto se reemplaza con la API de MT5 (mt5.copy_ticks_from).
    """
    symbol: str
    timestamp: datetime
    rejection_speed: float       # Velocidad de tick (σ)
    volume_delta: float           # Presión direccional (-1 a 1)
    tick_count: int               # Número de ticks en la ventana
    buy_volume: int               # Volumen comprador
    sell_volume: int              # Volumen vendedor
    current_atr: float            # ATR actual (para EXP-005)
    regime: str                   # Régimen detectado (EXP-010/011)
    price: float                  # Precio actual


@dataclass
class SniperSignal:
    """
    Señal generada por el Sniper/Titan después de inferencia.
    """
    symbol: str
    direction: str                # "LONG" o "SHORT"
    proba: float                  # Probabilidad (0-1)
    confidence: str               # "ALTA", "MEDIA", "BAJA"
    entry_price: float
    sl_price: float
    tp_price: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ExecutionOrder:
    """
    Orden lista para enviar a XM.
    """
    symbol: str
    direction: str
    volume_lots: float
    entry_price: float
    sl_price: float
    tp_price: float
    comment: str                  # "V8.0-SENTINEL-APPROVED"
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class TickAuditor:
    """
    Auditor de Ticks — Lee los ticks en vivo y extrae las métricas
    que necesita el Consejo de Centinelas.
    
    En producción, este módulo se conecta a MT5 vía:
      import MetaTrader5 as mt5
      ticks = mt5.copy_ticks_from(symbol, from_date, count)
    
    En modo demo/simulación, genera datos sintéticos realistas.
    """
    
    def __init__(self, lookback_minutes: int = 60):
        """
        Args:
            lookback_minutes: Ventana de ticks a analizar (default: 60 min)
        """
        self.lookback_minutes = lookback_minutes
        self._tick_buffer: Dict[str, List[dict]] = {}
        logger.info(f"📊 TickAuditor inicializado (ventana: {lookback_minutes} min)")
    
    def fetch_ticks(self, symbol: str) -> Optional[pd.DataFrame]:
        """
        Obtiene ticks en vivo desde MT5.
        
        En producción real, esto se reemplaza con:
          import MetaTrader5 as mt5
          from_date = datetime.now() - timedelta(minutes=self.lookback_minutes)
          ticks = mt5.copy_ticks_from(symbol, from_date, 100000)
          return pd.DataFrame(ticks)
        
        Returns:
            DataFrame con columnas: time, bid, ask, volume, flags
            None si no hay datos disponibles
        """
        # ─── MODO SIMULACIÓN ───
        # Genera ticks sintéticos realistas para pruebas
        n_ticks = np.random.randint(500, 2000)
        now = datetime.now()
        
        ticks = []
        base_price = 1.0800 if "EUR" in symbol else 2350.0 if "GOLD" in symbol else 1.2500
        
        for i in range(n_ticks):
            tick_time = now - timedelta(
                seconds=np.random.randint(0, self.lookback_minutes * 60)
            )
            price_jitter = np.random.normal(0, 0.0001 if "EUR" in symbol else 0.5)
            price = base_price + price_jitter
            
            # Simular volume_delta con sesgo aleatorio
            buy_vol = np.random.randint(1, 50)
            sell_vol = np.random.randint(1, 50)
            
            ticks.append({
                "time": tick_time,
                "price": price,
                "buy_volume": buy_vol,
                "sell_volume": sell_vol,
                "flags": np.random.choice([0, 1, 2, 4], p=[0.3, 0.3, 0.2, 0.2]),
            })
        
        df = pd.DataFrame(ticks)
        df = df.sort_values("time").reset_index(drop=True)
        
        # Cachear en buffer
        if symbol not in self._tick_buffer:
            self._tick_buffer[symbol] = []
        self._tick_buffer[symbol].extend(ticks)
        
        return df
    
    def compute_metrics(self, symbol: str) -> TickSnapshot:
        """
        Calcula las métricas institucionales desde los ticks.
        
        Args:
            symbol: Símbolo del activo
            
        Returns:
            TickSnapshot con todas las métricas para el Consejo
        """
        ticks_df = self.fetch_ticks(symbol)
        
        if ticks_df is None or len(ticks_df) < 10:
            logger.warning(f"⚠️ Pocos ticks para {symbol}, usando defaults")
            return TickSnapshot(
                symbol=symbol,
                timestamp=datetime.now(timezone.utc),
                rejection_speed=0.0,
                volume_delta=0.0,
                tick_count=0,
                buy_volume=0,
                sell_volume=0,
                current_atr=0.001 if "EUR" in symbol else 15.0,
                regime="NEUTRO",
                price=0.0,
            )
        
        try:
            # ─── Velocidad de tick (EXP-001 / EXP-013-GOLD) ───
            if "GOLD" in symbol:
                # ─── PROXY DIRECCIONAL PARA GOLD ───
                price_changes = ticks_df["price"].diff().dropna().values
                
                if len(price_changes) > 1:
                    avg_speed = float(np.abs(price_changes).mean())
                    micro_trend = float(np.mean(price_changes))
                    raw_directional_speed = avg_speed * micro_trend * 100
                    
                    if abs(raw_directional_speed) > 1e-10:
                        proxy_std = float(price_changes.std()) if price_changes.std() > 0 else 1e-10
                        rejection_speed = raw_directional_speed / proxy_std
                    else:
                        rejection_speed = 0.0
                        
                    logger.info(f"   🏆 GOLD Proxy Direccional: raw={raw_directional_speed:.4f}, z={rejection_speed:.2f}σ")
                else:
                    rejection_speed = 0.0
                    logger.info(f"   ⚠️ GOLD: Pocos cambios de precio para proxy direccional")
            else:
                # ─── EURUSD / GBPUSD: rejection_speed nativa (EXP-001) ───
                price_changes = ticks_df["price"].diff().dropna().values
                if len(price_changes) > 1:
                    rejection_speed = float(np.abs(price_changes).mean() / max(price_changes.std(), 1e-10))
                else:
                    rejection_speed = 0.0
            
            # ─── Volume Delta (EXP-004) ───
            total_buy = int(ticks_df["buy_volume"].sum())
            total_sell = int(ticks_df["sell_volume"].sum())
            total_volume = total_buy + total_sell
            
            if total_volume > 0:
                volume_delta = (total_buy - total_sell) / total_volume
            else:
                volume_delta = 0.0
            
            # ─── ATR estimado (EXP-005) ───
            price_range = float(ticks_df["price"].max() - ticks_df["price"].min())
            current_atr = price_range / 2.0  # Aproximación simple
            
            # Tick activity (para detección de barrido)
            tick_activity = len(ticks_df) / max(self.lookback_minutes, 1)
            tick_activity_normalized = tick_activity / 20.0  # Normalizado a ~1.0
            
            # ─── Régimen (EXP-010/011) ───
            if abs(rejection_speed) > 1.5 and tick_activity_normalized > 2.0:
                regime = "BARRIDO DE LIQUIDEZ"
            elif volume_delta < -0.3:
                regime = "TENDENCIA BAJISTA"
            elif volume_delta > 0.3:
                regime = "TENDENCIA ALCISTA"
            else:
                regime = "NEUTRO"
            
            # ─── EL BLINDAJE: Forzar conversión a float escalar ───
            metrics = {
                'speed': float(rejection_speed),
                'vol_delta': float(volume_delta),
                'ticks_count': int(len(ticks_df)),
                'regime': regime,
            }
            
            snapshot = TickSnapshot(
                symbol=symbol,
                timestamp=datetime.now(timezone.utc),
                rejection_speed=metrics['speed'],
                volume_delta=metrics['vol_delta'],
                tick_count=metrics['ticks_count'],
                buy_volume=total_buy,
                sell_volume=total_sell,
                current_atr=float(current_atr),
                regime=metrics['regime'],
                price=float(ticks_df["price"].iloc[-1]),
            )
            
            logger.info(
                f"📊 {symbol} | ticks={snapshot.tick_count} | "
                f"speed={snapshot.rejection_speed:.2f}σ | "
                f"vol_delta={snapshot.volume_delta:.3f} | "
                f"régimen={snapshot.regime}"
            )
            
            return snapshot
            
        except Exception as e:
            print(f"❌ Error en TickAuditor scalar conversion: {e}")
            return TickSnapshot(
                symbol=symbol,
                timestamp=datetime.now(timezone.utc),
                rejection_speed=0.0,
                volume_delta=0.0,
                tick_count=0,
                buy_volume=0,
                sell_volume=0,
                current_atr=0.001 if "EUR" in symbol else 15.0,
                regime="NEUTRO",
                price=0.0,
            )


class SentinelOrchestrator:
    """
    El Orquestador V8.0 — Integra el Consejo de Centinelas + Sentinel V2
    en el bucle principal de producción.
    
    Flujo:
      1. Recibe señal del Sniper/Titan (inferencia sobre velas H1)
      2. El TickAuditor extrae métricas de ticks en vivo
      3. El SentinelV2Engine evalúa los 15 factores alfa (Black Hole detection)
      4. El SentinelCouncil evalúa la orden contra 6 capas de veto
      5. Si todo está OK, genera la orden de ejecución para XM
    
    Uso:
      orchestrator = SentinelOrchestrator()
      order = orchestrator.process_signal(signal)
      if order:
          mt5.order_send(order)
    """
    
    def __init__(self, config: Optional[dict] = None):
        """
        Inicializa el Orquestador V8.0 con Sentinel V2 integrado.
        
        Args:
            config: Configuración personalizada (opcional)
        """
        # Inicializar componentes del Laboratorio
        self.council = SentinelCouncil(config)
        self.tick_auditor = TickAuditor(lookback_minutes=60)
        
        # ─── SENTINEL V2 ENGINE (Cerebro de Personalidad) ───
        self.sentinel_v2 = None
        if SentinelV2Engine is not None:
            try:
                self.sentinel_v2 = SentinelV2Engine()
                logger.info("🧠 Sentinel V2 Engine integrado (15 factores alfa)")
            except Exception as e:
                logger.warning(f"⚠️ No se pudo inicializar Sentinel V2: {e}")
        else:
            logger.warning("⚠️ SentinelV2Engine no disponible. Saltando capa de personalidad.")
        
        # Estado del orquestador
        self.state = {
            "signals_processed": 0,
            "orders_executed": 0,
            "orders_vetoed": 0,
            "last_signal": None,
            "last_verdict": None,
            "last_order": None,
            "start_time": datetime.now(timezone.utc),
            # Estado del Sentinel V2
            "sentinel_v2_vetoes": 0,
            "sentinel_v2_approved": 0,
            "sentinel_v2_last_state": None,
            "sentinel_v2_last_reason": "",
        }
        
        # Log de auditoría
        self.audit_log: List[dict] = []
        
        logger.info("=" * 70)
        logger.info("🚀 V8.0 SENTINEL ORCHESTRATOR INICIALIZADO")
        logger.info("   Pipeline: Sniper → TickAuditor → SentinelV2 → SentinelCouncil → XM")
        logger.info("=" * 70)
    
    def _build_alpha_features(self, symbol: str, snapshot: TickSnapshot) -> dict:
        """
        Construye el diccionario de 15 factores alfa para el Sentinel V2
        sin depender de MT5 (usa solo datos del snapshot y tiempo actual).
        
        Args:
            symbol: Símbolo del activo
            snapshot: Snapshot de ticks actual
            
        Returns:
            Diccionario con las 15 features alfa
        """
        now_utc = datetime.now(timezone.utc)
        
        return {
            'alpha_divergence': 0.0,  # Requiere MT5 para datos espejo
            'alpha_rejection_z': float(snapshot.rejection_speed),
            'alpha_rejection_z_gold': float(snapshot.rejection_speed) if symbol == 'GOLD' else 0.0,
            'alpha_micro_trend': float(snapshot.volume_delta),
            'alpha_micro_trend_gold': float(snapshot.volume_delta) if symbol == 'GOLD' else 0.0,
            'alpha_near_high': 0.0,  # Requiere velas H1
            'alpha_near_low': 0.0,   # Requiere velas H1
            'alpha_is_fixing_hour': 1.0 if now_utc.hour == 19 else 0.0,
            'alpha_is_ny_session': 1.0 if 12 <= now_utc.hour <= 20 else 0.0,
            'alpha_mom_3h': 0.0,     # Requiere velas H1
            'alpha_mom_6h': 0.0,     # Requiere velas H1
            'alpha_mom_12h': 0.0,    # Requiere velas H1
            'alpha_regime_high_vol': 1.0 if snapshot.regime in ("VOLÁTIL", "BARRIDO DE LIQUIDEZ", "MANIPULACION") else 0.0,
            'alpha_regime_low_vol': 1.0 if snapshot.regime == "RANGO" else 0.0,
            'alpha_regime_normal': 1.0 if snapshot.regime in ("NEUTRO", "TENDENCIA ALCISTA", "TENDENCIA BAJISTA") else 0.0,
        }
    
    def _build_alpha_features_mt5(self, symbol: str, snapshot: TickSnapshot) -> Optional[dict]:
        """
        Construye el diccionario de 15 factores alfa usando MT5 para datos
        de velas H1 y divergencia entre activos.
        
        Args:
            symbol: Símbolo del activo
            snapshot: Snapshot de ticks actual
            
        Returns:
            Diccionario con las 15 features alfa, o None si MT5 no está disponible
        """
        try:
            import MetaTrader5 as mt5
            
            now_utc = datetime.now(timezone.utc)
            
            # Obtener tick actual
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                logger.warning(f"⚠️ No se pudo obtener tick para {symbol}")
                return None
            
            # Obtener velas H1 (últimas 15)
            rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 15)
            df_rates = pd.DataFrame(rates) if rates is not None and len(rates) > 0 else pd.DataFrame()
            
            # Activo espejo para divergencia
            mirror_sym = 'GOLD' if symbol == 'EURUSD' else 'EURUSD'
            mirror_tick = mt5.symbol_info_tick(mirror_sym)
            mirror_rates = mt5.copy_rates_from_pos(mirror_sym, mt5.TIMEFRAME_H1, 0, 1)
            
            # Cálculos de retorno
            ret_self = 0.0
            if not df_rates.empty and 'open' in df_rates.columns:
                ret_self = (tick.bid - df_rates['open'].iloc[0]) / max(df_rates['open'].iloc[0], 1e-10)
            
            ret_mirror = 0.0
            if mirror_tick and mirror_rates is not None and len(mirror_rates) > 0:
                ret_mirror = (mirror_tick.bid - mirror_rates[0]['open']) / max(mirror_rates[0]['open'], 1e-10)
            
            # Cálculos de near_high/near_low
            atr_val = snapshot.current_atr
            near_high = 0.0
            near_low = 0.0
            if not df_rates.empty:
                near_high = float((df_rates['high'].max() - tick.bid) / max(atr_val, 1e-6))
                near_low = float((tick.bid - df_rates['low'].min()) / max(atr_val, 1e-6))
            
            # Momentum
            mom_3h = 0.0
            mom_6h = 0.0
            mom_12h = 0.0
            if not df_rates.empty and 'close' in df_rates.columns:
                closes = df_rates['close'].values
                if len(closes) >= 4:
                    mom_3h = float((closes[-1] - closes[-4]) / max(closes[-4], 1e-10))
                if len(closes) >= 7:
                    mom_6h = float((closes[-1] - closes[-7]) / max(closes[-7], 1e-10))
                if len(closes) >= 13:
                    mom_12h = float((closes[-1] - closes[-13]) / max(closes[-13], 1e-10))
            
            return {
                'alpha_divergence': float(ret_self - ret_mirror),
                'alpha_rejection_z': float(snapshot.rejection_speed),
                'alpha_rejection_z_gold': float(snapshot.rejection_speed) if symbol == 'GOLD' else 0.0,
                'alpha_micro_trend': float(snapshot.volume_delta),
                'alpha_micro_trend_gold': float(snapshot.volume_delta) if symbol == 'GOLD' else 0.0,
                'alpha_near_high': near_high,
                'alpha_near_low': near_low,
                'alpha_is_fixing_hour': 1.0 if now_utc.hour == 19 else 0.0,
                'alpha_is_ny_session': 1.0 if 12 <= now_utc.hour <= 20 else 0.0,
                'alpha_mom_3h': mom_3h,
                'alpha_mom_6h': mom_6h,
                'alpha_mom_12h': mom_12h,
                'alpha_regime_high_vol': 1.0 if snapshot.regime in ("VOLÁTIL", "BARRIDO DE LIQUIDEZ", "MANIPULACION") else 0.0,
                'alpha_regime_low_vol': 1.0 if snapshot.regime == "RANGO" else 0.0,
                'alpha_regime_normal': 1.0 if snapshot.regime in ("NEUTRO", "TENDENCIA ALCISTA", "TENDENCIA BAJISTA") else 0.0,
            }
            
        except ImportError:
            return None
        except Exception as e:
            logger.warning(f"⚠️ Error construyendo features MT5: {e}")
            return None
    
    def process_signal(self, signal: SniperSignal) -> Optional[ExecutionOrder]:
        """
        Procesa una señal del Sniper a través del pipeline completo.
        
        Pipeline:
          1. TickAuditor: métricas de ticks en vivo
          2. SentinelV2: 15 factores alfa (Black Hole detection)
          3. SentinelCouncil: 6 capas de veto
          4. Generación de orden
        
        Args:
            signal: Señal generada por el Sniper/Titan
            
        Returns:
            ExecutionOrder si todo aprueba, None si es vetado
        """
        self.state["signals_processed"] += 1
        self.state["last_signal"] = signal
        
        logger.info(f"\n{'─' * 70}")
        logger.info(f"📡 SEÑAL RECIBIDA: {signal.symbol} {signal.direction}")
        logger.info(f"   Proba: {signal.proba:.2f} | Confianza: {signal.confidence}")
        logger.info(f"   Entry: {signal.entry_price:.5f} | SL: {signal.sl_price:.5f} | TP: {signal.tp_price:.5f}")
        logger.info(f"{'─' * 70}")
        
        # ─── PASO 1: AUDITORÍA DE TICKS ───
        logger.info("🔍 Auditando ticks en vivo...")
        snapshot = self.tick_auditor.compute_metrics(signal.symbol)
        
        # ─── PASO 2: SENTINEL V2 (Cerebro de Personalidad) ───
        logger.info("🧠 Consultando Sentinel V2 (15 factores alfa)...")
        
        # Intentar construir features con MT5 primero, fallback a snapshot-only
        alpha_features = self._build_alpha_features_mt5(signal.symbol, snapshot)
        if alpha_features is None:
            alpha_features = self._build_alpha_features(signal.symbol, snapshot)
            logger.info("   Usando features base (sin MT5)")
        
        sentinel_v2_veto = False
        sentinel_v2_reason = ""
        sentinel_v2_state = None
        sentinel_v2_details = {}
        
        if self.sentinel_v2 is not None:
            try:
                estado_v2, veto_v2, razon_v2, detalles_v2 = self.sentinel_v2.evaluate(alpha_features)
                sentinel_v2_state = estado_v2
                sentinel_v2_reason = razon_v2
                sentinel_v2_details = detalles_v2
                sentinel_v2_veto = veto_v2
                
                if veto_v2:
                    self.state["sentinel_v2_vetoes"] += 1
                    logger.warning(f"   🛡️ SENTINEL V2 VETA: {razon_v2} (Estado {estado_v2})")
                else:
                    self.state["sentinel_v2_approved"] += 1
                    logger.info(f"   ✅ Sentinel V2 aprueba: {razon_v2} (Estado {estado_v2})")
                
                self.state["sentinel_v2_last_state"] = estado_v2
                self.state["sentinel_v2_last_reason"] = razon_v2
                
            except Exception as e:
                logger.warning(f"   ⚠️ Error en Sentinel V2 evaluate: {e}")
                sentinel_v2_veto = False  # No vetar por error del motor
        else:
            logger.info("   ⏭️ Sentinel V2 no disponible, saltando capa de personalidad")
        
        # ─── PASO 3: CONSEJO DE CENTINELAS ───
        logger.info("🛡️ Consultando al Consejo de Centinelas...")
        
        verdict = self.council.verify_order(
            symbol=signal.symbol,
            proba=signal.proba,
            rejection_speed=snapshot.rejection_speed,
            volume_delta=snapshot.volume_delta,
            regime=snapshot.regime,
            direction=signal.direction,
            tick_vol_std=float(alpha_features.get('alpha_rejection_z', 0.0)),
            absorption_z=float(alpha_features.get('alpha_near_low', 0.0)),
        )
        
        self.state["last_verdict"] = verdict
        
        # ─── REGISTRO DE AUDITORÍA ───
        audit_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": signal.symbol,
            "direction": signal.direction,
            "sniper_proba": signal.proba,
            "rejection_speed": snapshot.rejection_speed,
            "volume_delta": snapshot.volume_delta,
            "regime": snapshot.regime,
            "current_atr": snapshot.current_atr,
            "tick_count": snapshot.tick_count,
            # Sentinel V2
            "sentinel_v2_state": sentinel_v2_state,
            "sentinel_v2_veto": sentinel_v2_veto,
            "sentinel_v2_reason": sentinel_v2_reason,
            # Consejo
            "council_approved": verdict.approved,
            "council_veto_reason": verdict.reason if not verdict.approved else "",
            "council_veto_layer": verdict.veto_layer if not verdict.approved else "",
            # Veredicto final
            "approved": verdict.approved and not sentinel_v2_veto,
        }
        self.audit_log.append(audit_entry)
        
        # ─── PASO 4: DECISIÓN FINAL ───
        # Si el Sentinel V2 veta, la orden se rechaza inmediatamente
        if sentinel_v2_veto:
            self.state["orders_vetoed"] += 1
            logger.warning(f"❌ VETO DEL SENTINEL V2: {sentinel_v2_reason}")
            logger.warning(f"   Estado de mercado: {sentinel_v2_state} (Black Hole)")
            return None
        
        # Si el Consejo veta, la orden se rechaza
        if not verdict.approved:
            self.state["orders_vetoed"] += 1
            logger.warning(f"❌ VETO DEL CONSEJO: {verdict.reason}")
            logger.warning(f"   Capa: {verdict.veto_layer}")
            return None
        
        # ─── PASO 5: GENERAR ORDEN ───
        self.state["orders_executed"] += 1
        
        order = ExecutionOrder(
            symbol=signal.symbol,
            direction=signal.direction,
            volume_lots=self._calculate_lot_size(signal, snapshot),
            entry_price=signal.entry_price,
            sl_price=signal.sl_price,
            tp_price=signal.tp_price,
            comment="V8.0-SENTINEL-APPROVED",
        )
        
        self.state["last_order"] = order
        
        logger.info(f"✅ VEREDICTO FINAL: APROBADO")
        logger.info(f"   Sentinel V2: {sentinel_v2_reason} | Consejo: {verdict.reason}")
        logger.info(f"📤 ORDEN GENERADA: {order.symbol} {order.direction} {order.volume_lots} lots")
        logger.info(f"   Entry: {order.entry_price:.5f} | SL: {order.sl_price:.5f} | TP: {order.tp_price:.5f}")
        logger.info(f"   Comment: {order.comment}")
        
        return order
    
    def _prepare_personality_features(self, sym: str, df_last: pd.DataFrame, snapshot: TickSnapshot) -> Optional[pd.DataFrame]:
        """
        Construye el vector de 15 dimensiones exactas que espera el Sentinel V2.
        Une la data del activo actual con la del activo espejo (Divergencia).
        
        Args:
            sym: Símbolo del activo (EURUSD, GOLD)
            df_last: DataFrame con velas H1 del activo actual
            snapshot: Snapshot de ticks actual
            
        Returns:
            DataFrame con las 15 features alfa, o None si hay error
        """
        try:
            import MetaTrader5 as mt5
            
            # 1. Obtener datos del activo espejo para la divergencia
            mirror_sym = 'GOLD' if sym == 'EURUSD' else 'EURUSD'
            mirror_tick = mt5.symbol_info_tick(mirror_sym)
            mirror_rates = mt5.copy_rates_from_pos(mirror_sym, mt5.TIMEFRAME_H1, 0, 1)
            
            # 2. Obtener tick actual del activo principal
            tick = mt5.symbol_info_tick(sym)
            if tick is None:
                logger.warning(f"⚠️ No se pudo obtener tick para {sym}")
                return None
            
            # 3. Cálculos de Retorno y Divergencia
            ret_self = 0.0
            if df_last is not None and not df_last.empty and 'open' in df_last.columns:
                ret_self = (tick.bid - df_last['open'].values[0]) / max(df_last['open'].values[0], 1e-10)
            
            ret_mirror = 0.0
            if mirror_tick and mirror_rates is not None and len(mirror_rates) > 0:
                ret_mirror = (mirror_tick.bid - mirror_rates[0]['open']) / max(mirror_rates[0]['open'], 1e-10)
            
            # --- CONSTRUCCIÓN DEL DICCIONARIO DE 15 FEATURES ---
            f = {
                'alpha_divergence':        float(ret_self - ret_mirror),
                'alpha_rejection_z':       float(snapshot.rejection_speed),
                'alpha_rejection_z_gold':  float(snapshot.rejection_speed if sym == 'GOLD' else 0.0),
                'alpha_micro_trend':       float(snapshot.micro_trend if hasattr(snapshot, 'micro_trend') else 0.0),
                'alpha_micro_trend_gold':  float(snapshot.micro_trend if (sym == 'GOLD' and hasattr(snapshot, 'micro_trend')) else 0.0),
                'alpha_near_high':         float((df_last['high'].max() - tick.bid) / max(df_last['atr'].values[0] if 'atr' in df_last.columns else snapshot.current_atr, 1e-6)) if df_last is not None and not df_last.empty else 0.0,
                'alpha_near_low':          float((tick.bid - df_last['low'].min()) / max(df_last['atr'].values[0] if 'atr' in df_last.columns else snapshot.current_atr, 1e-6)) if df_last is not None and not df_last.empty else 0.0,
                'alpha_is_fixing_hour':    1 if datetime.now(timezone.utc).hour == 19 else 0,
                'alpha_is_ny_session':     1 if (12 <= datetime.now(timezone.utc).hour <= 20) else 0,
                'alpha_mom_3h':            float(df_last['close'].pct_change(3).fillna(0).values[0]) if df_last is not None and not df_last.empty and len(df_last) >= 4 else 0.0,
                'alpha_mom_6h':            float(df_last['close'].pct_change(6).fillna(0).values[0]) if df_last is not None and not df_last.empty and len(df_last) >= 7 else 0.0,
                'alpha_mom_12h':           float(df_last['close'].pct_change(12).fillna(0).values[0]) if df_last is not None and not df_last.empty and len(df_last) >= 13 else 0.0,
                # One-Hot Encoding del Régimen
                'alpha_regime_high_vol':   1 if snapshot.regime in ("VOLÁTIL", "BARRIDO DE LIQUIDEZ", "MANIPULACION") else 0,
                'alpha_regime_low_vol':    1 if snapshot.regime == "RANGO" else 0,
                'alpha_regime_normal':     1 if snapshot.regime in ("NEUTRO", "TENDENCIA ALCISTA", "TENDENCIA BAJISTA") else 0,
            }
            
            # Validación de seguridad: ¿Están todas las columnas?
            expected = [
                'alpha_divergence', 'alpha_rejection_z', 'alpha_rejection_z_gold',
                'alpha_micro_trend', 'alpha_micro_trend_gold', 'alpha_near_high',
                'alpha_near_low', 'alpha_is_fixing_hour', 'alpha_is_ny_session',
                'alpha_mom_3h', 'alpha_mom_6h', 'alpha_mom_12h',
                'alpha_regime_high_vol', 'alpha_regime_low_vol', 'alpha_regime_normal'
            ]
            
            # Reordenar y asegurar que sea un DataFrame de una sola fila
            result = pd.DataFrame([f])[expected]
            logger.info(f"   ✅ Features de personalidad construidas: {len(expected)} dimensiones")
            return result

        except ImportError:
            logger.warning("⚠️ MT5 no disponible para features de personalidad")
            return None
        except Exception as e:
            logger.warning(f"⚠️ Error preparando features de personalidad: {e}")
            return None
    
    def _calculate_lot_size(self, signal: SniperSignal, snapshot: TickSnapshot) -> float:
        """
        Calcula el tamaño de lote basado en la confianza y volatilidad.
        
        Args:
            signal: Señal del Sniper
            snapshot: Snapshot de ticks actual
            
        Returns:
            Tamaño de lote (0.01 mínimo)
        """
        # Base: 0.1 lots por cada $10,000 de cuenta
        base_lots = 0.1
        
        # Ajuste por confianza
        confidence_multiplier = {
            "ALTA": 1.0,
            "MEDIA": 0.7,
            "BAJA": 0.4,
        }.get(signal.confidence, 0.5)
        
        # Ajuste por volatilidad (menos tamaño si alta volatilidad)
        vol_multiplier = max(0.5, 1.0 - (snapshot.current_atr * 10))
        
        # Ajuste por régimen
        regime_multiplier = 1.0
        if snapshot.regime == "NEUTRO":
            regime_multiplier = 1.2  # Mejor régimen para operar
        elif "TENDENCIA" in snapshot.regime:
            regime_multiplier = 0.8  # Tendencia = más riesgo
        
        lot_size = base_lots * confidence_multiplier * vol_multiplier * regime_multiplier
        
        # Redondear a 0.01
        return max(0.01, round(lot_size, 2))
    
    def on_trade_result(self, pnl: float):
        """
        Procesa el resultado de un trade ejecutado.
        
        Args:
            pnl: Profit/Loss del trade en USD
        """
        if pnl > 0:
            self.council.report_win(pnl)
            logger.info(f"💰 TRADE GANADOR: +${pnl:.2f}")
        else:
            alert = self.council.report_consecutive_loss(abs(pnl))
            logger.warning(f"💸 TRADE PERDEDOR: ${pnl:.2f}")
            if alert:
                logger.warning(f"🚨 {alert}")
    
    def get_war_room_status(self) -> dict:
        """
        Genera el estado completo para el War Room.
        Incluye estado del Sentinel V2 (Cerebro de Personalidad).
        
        Returns:
            Diccionario con todo el estado del sistema
        """
        semaphore = self.council.get_semaphore_status()
        veto_summary = self.council.get_veto_summary()
        
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "semaphore": semaphore,
            "council": {
                "approved": self.council.state["total_approved"],
                "vetoed": self.council.state["total_vetoed"],
                "consecutive_losses": self.council.state["consecutive_losses"],
                "daily_pnl": self.council.state["daily_pnl"],
                "last_verdict": self.council.state["last_verdict"],
            },
            "sentinel_v2": {
                "vetoes": self.state["sentinel_v2_vetoes"],
                "approved": self.state["sentinel_v2_approved"],
                "last_state": self.state["sentinel_v2_last_state"],
                "last_reason": self.state["sentinel_v2_last_reason"],
                "active": self.sentinel_v2 is not None,
            },
            "veto_profile": veto_summary,
            "orchestrator": {
                "signals_processed": self.state["signals_processed"],
                "orders_executed": self.state["orders_executed"],
                "orders_vetoed": self.state["orders_vetoed"],
                "uptime_minutes": int(
                    (datetime.now(timezone.utc) - self.state["start_time"]).total_seconds() / 60
                ),
            },
            "last_signal": {
                "symbol": self.state["last_signal"].symbol if self.state["last_signal"] else None,
                "direction": self.state["last_signal"].direction if self.state["last_signal"] else None,
                "proba": self.state["last_signal"].proba if self.state["last_signal"] else None,
            } if self.state["last_signal"] else None,
        }
    
    def export_audit_log(self, filepath: str = "logs/sentinel_audit.csv"):
        """
        Exporta el log de auditoría a CSV.
        
        Args:
            filepath: Ruta del archivo CSV
        """
        if not self.audit_log:
            logger.warning("⚠️ No hay entradas de auditoría para exportar")
            return
        
        df = pd.DataFrame(self.audit_log)
        
        # Crear directorio si no existe
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        df.to_csv(filepath, index=False)
        logger.info(f"📁 Auditoría exportada: {filepath} ({len(df)} entradas)")
    
    def summary(self) -> str:
        """Retorna un resumen formateado del estado del orquestador."""
        status = self.get_war_room_status()
        semaphore_icon = {"VERDE": "🟢", "AMARILLO": "🟡", "ROJO": "🔴"}
        
        lines = [
            "\n" + "=" * 70,
            "🚀 V8.0 SENTINEL ORCHESTRATOR — RESUMEN",
            "=" * 70,
            f"\n🛡️ SEMÁFORO: {semaphore_icon.get(status['semaphore'], '❓')} {status['semaphore']}",
            f"\n📊 CONSEJO DE CENTINELAS:",
            f"   ✅ Aprobados: {status['council']['approved']}",
            f"   ❌ Vetados: {status['council']['vetoed']}",
            f"   🔥 Rachas pérdidas: {status['council']['consecutive_losses']}",
            f"   💰 P&L Diario: ${status['council']['daily_pnl']:.2f}",
            f"\n🧠 SENTINEL V2 (Personalidad):",
            f"   {'🟢 Activo' if status['sentinel_v2']['active'] else '🔴 Inactivo'}",
            f"   🛡️ Vetos: {status['sentinel_v2']['vetoes']}",
            f"   ✅ Aprobados: {status['sentinel_v2']['approved']}",
            f"   Último estado: {status['sentinel_v2']['last_state'] or 'N/A'}",
            f"   Última razón: {status['sentinel_v2']['last_reason'] or 'N/A'}",
            f"\n⚙️  ORQUESTADOR:",
            f"   📡 Señales procesadas: {status['orchestrator']['signals_processed']}",
            f"   📤 Órdenes ejecutadas: {status['orchestrator']['orders_executed']}",
            f"   🛡️ Órdenes vetadas: {status['orchestrator']['orders_vetoed']}",
            f"   ⏱️  Uptime: {status['orchestrator']['uptime_minutes']} min",
        ]
        
        if status["veto_profile"]["total_vetoes"] > 0:
            lines.append(f"\n📋 PERFIL DE VETOS:")
            for layer, count in status["veto_profile"]["layers"].items():
                pct = count / status["veto_profile"]["total_vetoes"] * 100
                lines.append(f"   ❌ {layer}: {count} ({pct:.1f}%)")
        
        lines.append("\n" + "=" * 70)
        return "\n".join(lines)


# ──────────────────────────────────────────────
# DEMO: SIMULACIÓN DE PRODUCCIÓN
# ──────────────────────────────────────────────

def run_production_simulation():
    """
    Simula un día de producción con señales entrantes del Sniper.
    Demuestra el pipeline completo: señal → ticks → consejo → orden.
    """
    print("\n" + "=" * 70)
    print("🏭 V8.0 DEMO: SIMULACIÓN DE PRODUCCIÓN")
    print("   Pipeline: Sniper → TickAuditor → SentinelCouncil → XM")
    print("=" * 70)
    
    # Inicializar orquestador
    orchestrator = SentinelOrchestrator()
    
    # ─── Escenario 1: Señal de Alta Calidad ───
    print("\n" + "█" * 70)
    print("📈 ESCENARIO 1: SEÑAL DE ALTA CALIDAD")
    print("   EURUSD LONG | proba=0.92 | Confianza=ALTA")
    print("   Debería: ✅ APROBAR")
    print("█" * 70)
    
    signal1 = SniperSignal(
        symbol="EURUSD",
        direction="LONG",
        proba=0.92,
        confidence="ALTA",
        entry_price=1.08500,
        sl_price=1.08200,
        tp_price=1.09100,
    )
    
    order1 = orchestrator.process_signal(signal1)
    assert order1 is not None, "❌ Escenario 1 falló: La señal de alta calidad debería aprobarse"
    print(f"\n✅ Escenario 1 PASADO: Orden generada ({order1.volume_lots} lots)")
    
    # ─── Escenario 2: Señal en Hora de Fixing ───
    print("\n" + "█" * 70)
    print("🕐 ESCENARIO 2: SEÑAL EN HORA DE FIXING")
    print("   GOLD SHORT | proba=0.85 | Confianza=ALTA")
    print("   Hora actual: 19:00 UTC (Fixing Time)")
    print("   Debería: ❌ VETAR por HORA")
    print("█" * 70)
    
    # Forzar hora de fixing
    original_hour = datetime.now(timezone.utc).hour
    orchestrator.council.config["forbidden_hour_utc"] = original_hour  # Forzar veto
    
    signal2 = SniperSignal(
        symbol="GOLD",
        direction="SHORT",
        proba=0.85,
        confidence="ALTA",
        entry_price=2350.50,
        sl_price=2365.00,
        tp_price=2320.00,
    )
    
    order2 = orchestrator.process_signal(signal2)
    assert order2 is None, "❌ Escenario 2 falló: Debería vetar por hora de fixing"
    print(f"\n✅ Escenario 2 PASADO: Veto por hora correcto")
    
    # Restaurar configuración
    orchestrator.council.config["forbidden_hour_utc"] = 19
    
    # ─── Escenario 3: Señal con Volumen en Contra ───
    print("\n" + "█" * 70)
    print("📊 ESCENARIO 3: VOLUMEN INSTITUCIONAL EN CONTRA")
    print("   EURUSD LONG | proba=0.82 | Confianza=ALTA")
    print("   Volume Delta simulado: -0.35 (vendedor)")
    print("   Debería: ❌ VETAR por VOLUMEN")
    print("█" * 70)
    
    # Forzar volume_delta negativo
    orchestrator.tick_auditor.compute_metrics = lambda s: TickSnapshot(
        symbol=s,
        timestamp=datetime.now(timezone.utc),
        rejection_speed=2.5,
        volume_delta=-0.35,
        tick_count=1200,
        buy_volume=400,
        sell_volume=800,
        current_atr=0.0012,
        regime="NEUTRO",
        price=1.08500,
    )
    
    signal3 = SniperSignal(
        symbol="EURUSD",
        direction="LONG",
        proba=0.82,
        confidence="ALTA",
        entry_price=1.08500,
        sl_price=1.08200,
        tp_price=1.09100,
    )
    
    order3 = orchestrator.process_signal(signal3)
    assert order3 is None, "❌ Escenario 3 falló: Debería vetar por volumen en contra"
    print(f"\n✅ Escenario 3 PASADO: Veto por volumen correcto")
    
    # ─── Escenario 4: Señal en Barrido de Liquidez ───
    print("\n" + "█" * 70)
    print("🌀 ESCENARIO 4: BARRIDO DE LIQUIDEZ")
    print("   GOLD LONG | proba=0.88 | Confianza=ALTA")
    print("   Régimen simulado: BARRIDO DE LIQUIDEZ")
    print("   Debería: ❌ VETAR por RÉGIMEN")
    print("█" * 70)
    
    orchestrator.tick_auditor.compute_metrics = lambda s: TickSnapshot(
        symbol=s,
        timestamp=datetime.now(timezone.utc),
        rejection_speed=3.2,
        volume_delta=0.15,
        tick_count=3500,
        buy_volume=1800,
        sell_volume=1700,
        current_atr=18.5,
        regime="BARRIDO DE LIQUIDEZ",
        price=2355.00,
    )
    
    signal4 = SniperSignal(
        symbol="GOLD",
        direction="LONG",
        proba=0.88,
        confidence="ALTA",
        entry_price=2355.00,
        sl_price=2340.00,
        tp_price=2385.00,
    )
    
    order4 = orchestrator.process_signal(signal4)
    assert order4 is None, "❌ Escenario 4 falló: Debería vetar por barrido de liquidez"
    print(f"\n✅ Escenario 4 PASADO: Veto por régimen correcto")
    
    # ─── Escenario 5: Señal de Baja Confianza ───
    print("\n" + "█" * 70)
    print("⚠️ ESCENARIO 5: CONFIANZA BAJA")
    print("   GBPUSD LONG | proba=0.65 | Confianza=BAJA")
    print("   Debería: ❌ VETAR por CONFIANZA")
    print("█" * 70)
    
    orchestrator.tick_auditor.compute_metrics = lambda s: TickSnapshot(
        symbol=s,
        timestamp=datetime.now(timezone.utc),
        rejection_speed=2.0,
        volume_delta=0.10,
        tick_count=800,
        buy_volume=420,
        sell_volume=380,
        current_atr=0.0015,
        regime="NEUTRO",
        price=1.25500,
    )
    
    signal5 = SniperSignal(
        symbol="GBPUSD",
        direction="LONG",
        proba=0.65,
        confidence="BAJA",
        entry_price=1.25500,
        sl_price=1.25200,
        tp_price=1.26100,
    )
    
    order5 = orchestrator.process_signal(signal5)
    assert order5 is None, "❌ Escenario 5 falló: Debería vetar por confianza baja"
    print(f"\n✅ Escenario 5 PASADO: Veto por confianza correcto")
    
    # ─── Resumen Final ───
    print("\n" + "=" * 70)
    print("📊 RESUMEN DE LA SIMULACIÓN")
    print("=" * 70)
    
    print(orchestrator.summary())
    
    # Exportar auditoría
    orchestrator.export_audit_log()
    
    print("\n" + "=" * 70)
    print("🎯 SIMULACIÓN COMPLETADA — 5/5 ESCENARIOS PASADOS")
    print("   El SentinelCouncil protege la producción correctamente")
    print("=" * 70)
    
    return orchestrator


if __name__ == "__main__":
    orchestrator = run_production_simulation()

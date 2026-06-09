"""
NEXUS QUANT LAB — V8.5 MASTER LIVE
====================================
stratum_v8_master_live.py

TERMINAL DE COMANDO — Full Chart Mode con Mapas de Guerra.

Pipeline completo:
  1. INFERENCIA: Cargar modelos .pkl (XGBoost + Alpha Factors)
  2. TICK AUDIT: TickAuditor lee ticks en vivo (MT5)
  3. CONSEJO: SentinelCouncil evalúa contra 6 capas de veto
  4. META-BRAIN V10: Capa de utilidad contextual (mercado + sistema + riesgo)
  5. MAPAS DE GUERRA: Gráficos de velas interactivos (Plotly) con:
     - Velas H1 en vivo
     - Zona de Oro (OTE 61.8%-78.6%)
     - Muros Púrpuras (D1 High/Low)
     - Símbolos $ de Sweep de Liquidez (LuxAlgo)
     - Swing Highs/Lows (Estructura de mercado)
     - Banner del Consejo en el título
  6. EJECUCIÓN: Si el Consejo + Meta-Brain aprueban, se envía la orden a XM

Activos gestionados:
  - EURUSD: war_room_eurusd.html
  - GOLD:   war_room_gold.html

Dependencias:
  pip install MetaTrader5 pandas numpy xgboost joblib plotly

Autor: Nexus Quant Lab
Fecha: 2026-06-09 (V8.5 — Meta-Brain V10.3 Integrado)
"""

import sys
import os
from datetime import datetime, timedelta, timezone
import time
import logging
import json
import webbrowser  # Abrir navegador automáticamente

# ─── SINCRONIZACIÓN DE RUTAS DEL LABORATORIO ───
root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if root_path not in sys.path:
    sys.path.insert(0, root_path)
os.chdir(root_path)
# ────────────────────────────────────────────────

import numpy as np
import pandas as pd

# ─── Importaciones del Laboratorio ───
from production.stratum_sentinel_orchestrator_v8 import (
    SentinelOrchestrator,
    SniperSignal,
    TickSnapshot,
)
from production.war_map_generator_v2 import generate_war_map
from production.strategy_engine import SMCEngine
from production.brain_client import BrainDockerClient
from core.meta_brain_v10 import MetaBrainV10

# ──────────────────────────────────────────────────────────────────────
# CONFIGURACIÓN DE COMBATE V8.5
# ──────────────────────────────────────────────────────────────────────
SYMBOL_LIST = ["EURUSD", "GOLD"]
THRESHOLD = 0.55          # Confianza mínima del Sniper
RISK_PER_TRADE = 0.01     # 1% de riesgo por trade
MAGIC_MASTER = 828282     # Magic Number para identificar órdenes del bot
AUDIT_LOG_PATH = "logs/sentinel_audit.csv"
MODEL_DIR = "models"

# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("StratumV8Master")


class ModelLoader:
    """
    Carga los modelos entrenados del Laboratorio.
    
    En producción, carga:
      - eurusd_alpha_brain_v2.pkl (XGBoost para EURUSD)
      - gold_alpha_brain_v2.pkl (XGBoost para GOLD)
      - market_pca_v2.pkl (PCA para features)
      - market_scaler_v2.pkl (Scaler para features)
      - eurusd_alpha_features_v2.json (Features para EURUSD)
      - gold_alpha_features_v2.json (Features para GOLD)
    """
    
    def __init__(self):
        self.models = {}
        self.scaler = None
        self.pca = None
        self.features = {}
        self._loaded = False
    
    def load_all(self):
        """Carga todos los modelos disponibles."""
        try:
            import joblib
            
            # Cargar modelos XGBoost
            for sym in ["EURUSD", "GOLD"]:
                model_key = f"{sym.lower()}_alpha_brain_v2"
                model_path = os.path.join(MODEL_DIR, f"{model_key}.pkl")
                if os.path.exists(model_path):
                    self.models[sym] = joblib.load(model_path)
                    logger.info(f"🧠 Modelo {sym} cargado: {model_path}")
                else:
                    logger.warning(f"⚠️ Modelo {sym} no encontrado: {model_path}")
            
            # Cargar scaler y PCA
            scaler_path = os.path.join(MODEL_DIR, "market_scaler_v2.pkl")
            if os.path.exists(scaler_path):
                self.scaler = joblib.load(scaler_path)
                logger.info(f"📐 Scaler cargado: {scaler_path}")
            
            pca_path = os.path.join(MODEL_DIR, "market_pca_v2.pkl")
            if os.path.exists(pca_path):
                self.pca = joblib.load(pca_path)
                logger.info(f"📉 PCA cargado: {pca_path}")
            
            # Cargar features
            for sym in ["EURUSD", "GOLD"]:
                feat_key = f"{sym.lower()}_alpha_features_v2"
                feat_path = os.path.join(MODEL_DIR, f"{feat_key}.json")
                if os.path.exists(feat_path):
                    with open(feat_path, "r") as f:
                        self.features[sym] = json.load(f)
                    logger.info(f"📋 Features {sym} cargados: {feat_path}")
            
            self._loaded = True
            logger.info("✅ Todos los modelos cargados exitosamente")
            
        except ImportError:
            logger.warning("⚠️ joblib no instalado. Usando modo simulación.")
        except Exception as e:
            logger.error(f"❌ Error cargando modelos: {e}")
    
    def predict(self, symbol: str, features: dict) -> tuple:
        """
        Realiza una predicción para un símbolo dado usando el pipeline 15→13.
        
        Args:
            symbol: Símbolo del activo
            features: Diccionario de features para la predicción (debe tener 15 claves)
            
        Returns:
            tuple: (dirección, probabilidad)
        """
        if not self._loaded or symbol not in self.models:
            return self._simulate_prediction(symbol)
        
        try:
            model = self.models[symbol]
            
            # PASO 1: Escalar con 15 dimensiones (scaler fue entrenado con one-hot regime)
            scaler_feature_names = self.scaler.feature_names_in_
            X_list_15d = [features.get(name, 0.0) for name in scaler_feature_names]
            X_15d = pd.DataFrame([X_list_15d], columns=scaler_feature_names)
            X_scaled_15d = self.scaler.transform(X_15d)
            
            # PASO 2: Colapsar one-hot (3 columnas) a feature única 'alpha_regime' para el modelo
            model_feature_names = model.feature_names_in_
            X_scaled_df = pd.DataFrame(X_scaled_15d, columns=scaler_feature_names)
            
            # Colapsar one-hot regime a feature única
            regime_map = {
                'alpha_regime_high_vol': 'ALTA VOLATILIDAD',
                'alpha_regime_low_vol': 'BAJA VOLATILIDAD',
                'alpha_regime_normal': 'NEUTRO',
            }
            active_regime = 'NEUTRO'
            for col, regime_name in regime_map.items():
                if X_scaled_df[col].iloc[0] > 0.5:
                    active_regime = regime_name
                    break
            
            # Construir vector de 13 features para el modelo
            X_model_dict = {}
            for name in model_feature_names:
                if name == 'alpha_regime':
                    if active_regime == 'ALTA VOLATILIDAD':
                        X_model_dict[name] = X_scaled_df['alpha_regime_high_vol'].iloc[0]
                    elif active_regime == 'BAJA VOLATILIDAD':
                        X_model_dict[name] = X_scaled_df['alpha_regime_low_vol'].iloc[0]
                    else:
                        X_model_dict[name] = X_scaled_df['alpha_regime_normal'].iloc[0]
                else:
                    X_model_dict[name] = X_scaled_df[name].iloc[0]
            
            X_model = pd.DataFrame([X_model_dict], columns=model_feature_names)
            proba = model.predict_proba(X_model)[0][1]
            direction = "LONG" if proba > 0.5 else "SHORT"
            
            return direction, max(proba, 1 - proba)
            
        except Exception as e:
            logger.error(f"❌ Error en predicción {symbol}: {e}")
            return self._simulate_prediction(symbol)
    
    def _simulate_prediction(self, symbol: str) -> tuple:
        """Genera una señal sintética para simulación."""
        proba = np.random.uniform(0.6, 0.95)
        direction = "LONG" if np.random.random() > 0.5 else "SHORT"
        return direction, proba


class MT5Connector:
    """
    Conector a MetaTrader 5 para operaciones en vivo.
    
    Maneja:
      - Inicialización y shutdown de MT5
      - Obtención de precios en tiempo real
      - Obtención de velas H1 y D1 para los mapas
      - Envío de órdenes
      - Gestión de posiciones abiertas
    """
    
    def __init__(self, magic: int = MAGIC_MASTER):
        self.magic = magic
        self.connected = False
    
    def initialize(self) -> bool:
        """Inicializa la conexión con MT5."""
        try:
            import MetaTrader5 as mt5
            
            if not mt5.initialize():
                logger.error(f"❌ MT5 initialize() falló: {mt5.last_error()}")
                return False
            
            self.connected = True
            logger.info("✅ MT5 conectado exitosamente")
            
            account_info = mt5.account_info()
            if account_info:
                logger.info(f"   Cuenta: {account_info.login} | "
                           f"Balance: ${account_info.balance:.2f} | "
                           f"Apalancamiento: 1:{account_info.leverage}")
            
            return True
            
        except ImportError:
            logger.warning("⚠️ MetaTrader5 no instalado. Usando modo simulación.")
            return False
        except Exception as e:
            logger.error(f"❌ Error conectando MT5: {e}")
            return False
    
    def get_rates(self, symbol: str, timeframe: int, count: int = 100) -> pd.DataFrame:
        """
        Obtiene velas de MT5.
        
        Args:
            symbol: Símbolo del activo
            timeframe: Marco temporal (mt5.TIMEFRAME_H1, mt5.TIMEFRAME_D1, etc.)
            count: Número de velas a obtener
            
        Returns:
            DataFrame con columnas: time, open, high, low, close, tick_volume, spread, real_volume
        """
        try:
            import MetaTrader5 as mt5
            
            rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
            if rates is None or len(rates) == 0:
                logger.warning(f"⚠️ No se pudieron obtener velas para {symbol}")
                return pd.DataFrame()
            
            df = pd.DataFrame(rates)
            df['time'] = pd.to_datetime(df['time'], unit='s')
            return df
            
        except Exception as e:
            logger.error(f"❌ Error obteniendo velas {symbol}: {e}")
            return pd.DataFrame()
    
    def get_tick(self, symbol: str) -> tuple:
        """
        Obtiene el tick actual de un símbolo.
        
        Returns:
            tuple: (bid, ask, spread)
        """
        try:
            import MetaTrader5 as mt5
            
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                return (0.0, 0.0, 0.0)
            
            spread_actual = abs(tick.ask - tick.bid)
            return (tick.bid, tick.ask, spread_actual)
            
        except Exception as e:
            logger.error(f"❌ Error obteniendo tick {symbol}: {e}")
            return (0.0, 0.0, 0.0)
    
    def send_order(self, order) -> bool:
        """Envía una orden a MT5."""
        try:
            import MetaTrader5 as mt5
            
            order_type = mt5.ORDER_TYPE_BUY if order.direction == "LONG" else mt5.ORDER_TYPE_SELL
            
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": order.symbol,
                "volume": order.volume_lots,
                "type": order_type,
                "price": order.entry_price,
                "sl": order.sl_price,
                "tp": order.tp_price,
                "deviation": 10,
                "magic": self.magic,
                "comment": order.comment,
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            
            result = mt5.order_send(request)
            
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                logger.error(f"❌ Orden rechazada: {result.comment} (código: {result.retcode})")
                return False
            
            logger.info(f"✅ Orden ejecutada: {order.symbol} {order.direction} "
                       f"{order.volume_lots} lots @ {order.entry_price}")
            logger.info(f"   Ticket: {result.order} | SL: {order.sl_price} | TP: {order.tp_price}")
            
            return True
            
        except ImportError:
            logger.warning(f"⚠️ [SIMULACIÓN] Orden lista: {order.symbol} {order.direction} "
                          f"{order.volume_lots} lots @ {order.entry_price}")
            return True
        except Exception as e:
            logger.error(f"❌ Error enviando orden: {e}")
            return False
    
    def get_open_positions(self, symbol: str = None) -> list:
        """Obtiene posiciones abiertas."""
        try:
            import MetaTrader5 as mt5
            
            if symbol:
                positions = mt5.positions_get(symbol=symbol)
            else:
                positions = mt5.positions_get()
            
            return positions or []
            
        except ImportError:
            return []
        except Exception as e:
            logger.error(f"❌ Error obteniendo posiciones: {e}")
            return []
    
    def close_position(self, position) -> bool:
        """Cierra una posición específica."""
        try:
            import MetaTrader5 as mt5
            
            tick = mt5.symbol_info_tick(position.symbol)
            if tick is None:
                return False
            
            order_type = mt5.ORDER_TYPE_SELL if position.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
            price = tick.bid if order_type == mt5.ORDER_TYPE_SELL else tick.ask
            
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": position.symbol,
                "volume": position.volume,
                "type": order_type,
                "position": position.ticket,
                "price": price,
                "deviation": 10,
                "magic": self.magic,
                "comment": "V8.5-CLOSE",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            
            result = mt5.order_send(request)
            return result.retcode == mt5.TRADE_RETCODE_DONE
            
        except ImportError:
            return True
        except Exception as e:
            logger.error(f"❌ Error cerrando posición: {e}")
            return False
    
    def shutdown(self):
        """Cierra la conexión con MT5."""
        try:
            import MetaTrader5 as mt5
            mt5.shutdown()
            self.connected = False
            logger.info("🔌 MT5 desconectado")
        except:
            pass


def get_alpha_vector_15d(df, symbol, audit_data, other_symbol_data=None):
    """
    Extrae los 15 factores Alfa sincronizados con el laboratorio (EXP-009 V2)
    
    El StandardScaler del laboratorio espera exactamente estos 15 nombres:
      alpha_divergence, alpha_rejection_z, alpha_rejection_z_gold,
      alpha_micro_trend, alpha_micro_trend_gold,
      alpha_near_high, alpha_near_low,
      alpha_is_fixing_hour, alpha_is_ny_session,
      alpha_mom_3h, alpha_mom_6h, alpha_mom_12h,
      alpha_regime_high_vol, alpha_regime_low_vol, alpha_regime_normal
    """
    import pandas as pd
    from datetime import datetime
    
    # 1. Datos de Sesión
    now_utc = datetime.now(timezone.utc)
    is_ny = 1 if (13 <= now_utc.hour <= 20) else 0
    is_fixing = 1 if (now_utc.hour == 19) else 0
    
    # 2. Datos de Proximidad (SMC)
    h24 = df['high'].iloc[-24:].max()
    l24 = df['low'].iloc[-24:].min()
    curr = df['close'].iloc[-1]
    near_high = (curr - l24) / (h24 - l24) if (h24 - l24) != 0 else 0.5
    near_low = 1 - near_high

    # 3. Momentum
    mom3 = df['close'].iloc[-1] / df['close'].iloc[-3] - 1 if len(df) > 3 else 0
    mom6 = df['close'].iloc[-1] / df['close'].iloc[-6] - 1 if len(df) > 6 else 0
    mom12 = df['close'].iloc[-1] / df['close'].iloc[-12] - 1 if len(df) > 12 else 0

    # 4. Régimen One-Hot (3 columnas exactas que espera el scaler)
    regime = audit_data.get('regime', 'NEUTRO')
    regime_high_vol = 1.0 if regime == 'ALTA VOLATILIDAD' else 0.0
    regime_low_vol = 1.0 if regime == 'BAJA VOLATILIDAD' else 0.0
    regime_normal = 1.0 if regime in ('NEUTRO', 'NORMAL') else 0.0

    # 5. Construir Diccionario Base (15 dimensiones exactas)
    factors = {
        'alpha_rejection_z': audit_data.get('speed', 0.0),
        'alpha_micro_trend': audit_data.get('vol_delta', 0.0),
        'alpha_regime_high_vol': regime_high_vol,
        'alpha_regime_low_vol': regime_low_vol,
        'alpha_regime_normal': regime_normal,
        'alpha_near_high': near_high,
        'alpha_near_low': near_low,
        'alpha_is_fixing_hour': is_fixing,
        'alpha_is_ny_session': is_ny,
        'alpha_mom_3h': mom3,
        'alpha_mom_6h': mom6,
        'alpha_mom_12h': mom12,
        'alpha_divergence': 0.0,  # Se llena con datos del otro activo
        'alpha_rejection_z_gold': 0.0,
        'alpha_micro_trend_gold': 0.0,
    }

    # 6. Llenar Cross-Asset (Divergencia)
    if other_symbol_data:
        factors['alpha_divergence'] = curr - other_symbol_data.get('close', curr)
        factors['alpha_rejection_z_gold'] = other_symbol_data.get('speed', 0.0)
        factors['alpha_micro_trend_gold'] = other_symbol_data.get('vol_delta', 0.0)

    return factors


def build_features_from_ticks(symbol: str, snapshot: TickSnapshot) -> dict:
    """
    Construye el vector de features para el modelo desde el snapshot de ticks.
    (DEPRECATED — Usar get_alpha_vector_15d en su lugar)
    """
    features = {
        "rejection_speed": snapshot.rejection_speed,
        "tick_count": snapshot.tick_count,
        "tick_activity": snapshot.tick_count / 60.0,
        "volume_delta": snapshot.volume_delta,
        "buy_volume": snapshot.buy_volume,
        "sell_volume": snapshot.sell_volume,
        "volume_imbalance": (snapshot.buy_volume - snapshot.sell_volume) / max(snapshot.buy_volume + snapshot.sell_volume, 1),
        "current_atr": snapshot.current_atr,
        "atr_percent": snapshot.current_atr / snapshot.price if snapshot.price > 0 else 0.0,
        "regime_neutro": 1.0 if snapshot.regime == "NEUTRO" else 0.0,
        "regime_tendencia_alcista": 1.0 if snapshot.regime == "TENDENCIA ALCISTA" else 0.0,
        "regime_tendencia_bajista": 1.0 if snapshot.regime == "TENDENCIA BAJISTA" else 0.0,
        "regime_barrido": 1.0 if snapshot.regime == "BARRIDO DE LIQUIDEZ" else 0.0,
        "price": snapshot.price,
        "hour_utc": datetime.now(timezone.utc).hour,
        "minute": datetime.now(timezone.utc).minute,
        "is_fixing_hour": 1.0 if 18 <= datetime.now(timezone.utc).hour <= 20 else 0.0,
    }
    return features


# ─── SMC SQUAD ENGINE (V8.5) ───
smc_engine = SMCEngine()


def execute_squad_logic(symbol: str, df: pd.DataFrame, audit: dict) -> dict:
    """
    Evalúa las señales SMC (BOS + Turtle Soup) y determina si hay
    un ataque SQUAD listo para ejecutar.
    
    Args:
        symbol: Símbolo del activo
        df: DataFrame con velas H1
        audit: Diccionario con métricas de auditoría (speed, vol_delta, etc.)
    
    Returns:
        dict con:
          - squad_attack: señal de Turtle Soup lista (si aplica)
          - squad_trend: señal de BOS lista (si aplica)
          - signals: lista de todas las señales detectadas
          - order_block: Order Block detectado (si aplica)
    """
    # Análisis completo SMC
    smc_result = smc_engine.analyze(df, audit)
    
    # Log de resultados
    if smc_result['squad_attack']:
        attack = smc_result['squad_attack']
        logger.info(f"🔥 SQUAD ATTACK: {attack['signal']['type']} detectado en {symbol} | "
                   f"speed={attack['speed']:.2f}σ | confianza={attack['confidence']}")
    
    if smc_result['squad_trend']:
        trend = smc_result['squad_trend']
        logger.info(f"🚀 SQUAD TREND: {trend['signal']['type']} confirmado en {symbol} | "
                   f"vol_delta={trend['vol_delta']:.3f} | confianza={trend['confidence']}")
    
    if smc_result['order_block']:
        ob = smc_result['order_block']
        logger.info(f"🧱 ORDER BLOCK: {ob['type']} en {symbol} | "
                   f"zona: {ob['ob_low']:.5f} - {ob['ob_high']:.5f}")
    
    return smc_result


def update_war_map(
    symbol: str,
    mt5_conn: MT5Connector,
    orchestrator: SentinelOrchestrator,
    state: dict,
    output_path: str,
):
    """
    Genera/actualiza el Mapa de Guerra para un símbolo.
    
    Obtiene velas H1 y D1 de MT5, calcula las capas visuales,
    e inyecta el veredicto del Consejo en el título.
    """
    try:
        import MetaTrader5 as mt5
        
        # Obtener velas H1 (100 velas para contexto)
        df_h1 = mt5_conn.get_rates(symbol, mt5.TIMEFRAME_H1, 100)
        if df_h1.empty:
            logger.warning(f"⚠️ No hay velas H1 para {symbol}. Saltando mapa.")
            return
        
        # ✅ NORMALIZAR ÍNDICE: Asegurar que sea datetime para evitar crash en OPEN DAY
        if 'time' in df_h1.columns:
            df_h1['time'] = pd.to_datetime(df_h1['time'], unit='s') if df_h1['time'].dtype.kind in ('i', 'f') else pd.to_datetime(df_h1['time'])
            df_h1.set_index('time', inplace=True)
        elif not pd.api.types.is_datetime64_any_dtype(df_h1.index):
            # Si el índice no es datetime, intentar convertir
            try:
                df_h1.index = pd.to_datetime(df_h1.index, unit='s')
            except (ValueError, TypeError):
                logger.warning(f"⚠️ {symbol}: No se pudo convertir índice a datetime. Usando índice original.")
        
        # Obtener velas D1 para niveles HTF
        df_d1 = mt5_conn.get_rates(symbol, mt5.TIMEFRAME_D1, 2)
        d1_high = df_d1['high'].iloc[0] if not df_d1.empty else 0.0
        d1_low = df_d1['low'].iloc[0] if not df_d1.empty else 0.0
        
        # Obtener tick actual
        bid, ask, spread = mt5_conn.get_tick(symbol)
        
        # Estado del símbolo
        sym_state = state.get(symbol, {
            'p': 0.0,
            'dir': 0,
            'atr': 0.0,
            'verdict': 'INIT',
            'reason': '',
        })
        
        # Detectar sweep en la última vela
        last_candle = df_h1.iloc[-1] if len(df_h1) > 0 else None
        sweep_detected = 0
        if last_candle is not None and len(df_h1) > 3:
            prev_high = df_h1['high'].iloc[-4:-1].max()
            prev_low = df_h1['low'].iloc[-4:-1].min()
            if last_candle['high'] > prev_high and last_candle['close'] < prev_high:
                sweep_detected = 1
            elif last_candle['low'] < prev_low and last_candle['close'] > prev_low:
                sweep_detected = 1
        
        # Calcular ATR simple (14 períodos)
        if len(df_h1) >= 14:
            tr = pd.DataFrame({
                'hl': df_h1['high'] - df_h1['low'],
                'hc': abs(df_h1['high'] - df_h1['close'].shift(1)),
                'lc': abs(df_h1['low'] - df_h1['close'].shift(1)),
            }).max(axis=1)
            atr_value = tr.tail(14).mean()
        else:
            atr_value = 0.001
        
        # Generar el mapa de guerra
        generate_war_map(
            df=df_h1,
            proba=sym_state['p'],
            direction=sym_state['dir'],
            sweep=sweep_detected,
            atr=atr_value,
            sw_high=df_h1['high'].iloc[-5:].max() if len(df_h1) >= 5 else 0,
            sw_low=df_h1['low'].iloc[-5:].min() if len(df_h1) >= 5 else 0,
            d1_high=d1_high,
            d1_low=d1_low,
            bid=bid,
            ask=ask,
            symbol=symbol,
            verdict=sym_state['verdict'],
            reason=sym_state['reason'],
            output_path=output_path,
        )
        
    except Exception as e:
        logger.error(f"❌ Error actualizando mapa de guerra {symbol}: {e}")


def main():
    """
    Punto de entrada principal del V8.5 Master Live.
    
    Ciclo de vida:
      1. Inicializar MT5, modelos, orquestador, Meta-Brain
      2. Abrir automáticamente los Mapas de Guerra en el navegador
      3. Cada hora: ciclo de inferencia y gobernanza (Consejo + Meta-Brain)
      4. Cada 30s: actualizar Mapas de Guerra con velas + capas visuales
      5. En shutdown: cerrar conexiones y exportar logs
    """
    logger.info("=" * 70)
    logger.info("🚀 DESPLEGANDO TERMINAL DE COMANDO V8.5 — FULL CHART MODE")
    logger.info("   Pipeline: Modelos → TickAuditor → SentinelCouncil → Meta-Brain V10 → Mapas de Guerra → XM")
    logger.info("=" * 70)
    
    # ─── 1. INICIALIZAR COMPONENTES ───
    
    # Conectar MT5
    mt5_conn = MT5Connector(magic=MAGIC_MASTER)
    mt5_connected = mt5_conn.initialize()
    
    if not mt5_connected:
        logger.warning("⚠️ MT5 no disponible. Ejecutando en MODO SIMULACIÓN.")
    
    # ─── [EXP-021] INICIALIZACIÓN CEREBRO DISTRIBUIDO ───
    # Estrategia: Docker-first. Solo cargamos modelos locales si Docker no responde.
    DOCKER_API_URL = "http://localhost:8000"
    use_docker = False
    model_loader = None
    
    # 1. Intentar conectar con Docker primero
    try:
        import requests
        response = requests.get(DOCKER_API_URL, timeout=2)
        if response.status_code == 200:
            use_docker = True
            logger.info("📡 [SISTEMA DISTRIBUIDO] Docker Brain API detectado y operativo.")
            logger.info("   🚫 Modelos .pkl NO se cargarán en Windows (ahorro de RAM).")
        else:
            logger.warning(f"⚠️ Docker respondió con status {response.status_code}. Usando fallback local.")
    except ImportError:
        logger.warning("⚠️ requests no instalado. Usando fallback local.")
    except Exception as e:
        logger.warning(f"⚠️ Docker Brain API no detectada: {e}")
        logger.warning("   Intentando carga local de modelos (Fallback)...")
    
    # 2. Carga local SOLO si Docker no está disponible
    if not use_docker:
        model_loader = ModelLoader()
        model_loader.load_all()
        if not model_loader._loaded:
            logger.error("❌ Error crítico: Ni Docker ni modelos locales disponibles.")
            logger.error("   El sistema no podrá realizar inferencias de IA.")
    else:
        # Crear ModelLoader vacío para que el código no falle al referenciarlo
        model_loader = ModelLoader()  # No llama a load_all(), queda con _loaded = False
    
    # Inicializar orquestador V8.0 (incluye Sentinel V2 internamente)
    orchestrator = SentinelOrchestrator()
    
    # ─── [FASE 10] INICIALIZAR META-BRAIN V10.3 ───
    meta_brain = MetaBrainV10(
        confidence_threshold=0.55,
        risk_per_trade=0.01,
        sl_atr=2.0,
        tp_atr=4.0,
    )
    logger.info("🧬 Meta-Brain V10.3 inicializado (Capa 1: Mercado | Capa 2: Sistema | Capa 3: Utilidad)")
    logger.info(f"   Límites: confianza=[0.45, 0.75] | riesgo=[0.25%, 2.5%] | SL=[1.0, 3.0]ATR | TP=[0.8, 4.0]ATR")
    
    # Estado compartido para los mapas
    state = {
        s: {
            'p': 0.0,
            'dir': 0,
            'atr': 0.0,
            'verdict': 'INIT',
            'reason': '',
        }
        for s in SYMBOL_LIST
    }
    
    # ─── 2. APERTURA AUTOMÁTICA DE MAPAS ───
    logger.info("🖥️  Abriendo pantallas del Centro de Mando...")
    for sym in SYMBOL_LIST:
        output_path = f"logs/war_room_{sym.lower()}.html"
        file_path = os.path.abspath(output_path)
        
        # Generar mapa inicial
        update_war_map(sym, mt5_conn, orchestrator, state, output_path)
        
        # Abrir en el navegador
        webbrowser.open(f"file://{file_path}")
        logger.info(f"🌐 {sym}: {file_path}")
    
    logger.info("🔥 Mapas de Guerra desplegados en el navegador.")
    
    # Estado del ciclo
    last_hour = -1
    last_update_second = -1
    start_time = datetime.now(timezone.utc)
    
    logger.info(f"\n📡 Monitoreando: {', '.join(SYMBOL_LIST)}")
    logger.info(f"🕒 Hora actual UTC: {datetime.now(timezone.utc).strftime('%H:%M:%S')}")
    logger.info(f"🕒 Hora Lima: {(datetime.now(timezone.utc) - timedelta(hours=5)).strftime('%H:%M:%S')}")
    logger.info(f"\n{'─' * 70}")
    logger.info("⏳ Esperando el próximo cierre de hora para el primer análisis...")
    logger.info(f"{'─' * 70}")
    
    try:
        # ─── 3. BUCLE PRINCIPAL ───
        while True:
            now_utc = datetime.now(timezone.utc)
            now_lima = now_utc - timedelta(hours=5)
            
            # ─── CADA HORA: CICLO DE INFERENCIA Y GOBERNANZA ───
            if now_utc.minute == 0 and now_utc.second <= 5 and now_utc.hour != last_hour:
                logger.info(f"\n{'█' * 70}")
                logger.info(f"🔔 [CIERRE DE HORA {now_utc.strftime('%H:00')} UTC / "
                           f"{now_lima.strftime('%H:00')} Lima]")
                logger.info(f"{'█' * 70}")
                
                # Verificar posiciones abiertas
                open_positions = mt5_conn.get_open_positions()
                if open_positions:
                    logger.info(f"📌 Posiciones abiertas: {len(open_positions)}")
                    for pos in open_positions:
                        logger.info(f"   {pos.symbol} {pos.type_str} {pos.volume} lots "
                                   f"@ {pos.price_open} | SL: {pos.sl} | TP: {pos.tp}")
                
                for symbol in SYMBOL_LIST:
                    try:
                        logger.info(f"\n{'─' * 40}")
                        logger.info(f"📊 Analizando {symbol}...")
                        
                        # ─── [FIX CRÍTICO V8.5.2] INICIALIZAR SniperSignal EN None ───
                        SniperSignal_local = None
                        
                        # A. Obtener precio actual
                        bid, ask, spread = mt5_conn.get_tick(symbol)
                        if bid == 0.0 and mt5_connected:
                            logger.warning(f"⚠️ {symbol}: No se pudo obtener precio, saltando")
                            continue
                        
                        # B. Obtener velas H1 para análisis SMC
                        import MetaTrader5 as mt5
                        df_h1 = mt5_conn.get_rates(symbol, mt5.TIMEFRAME_H1, 100)
                        
                        # C. Obtener predicción del modelo (Alpha Brain V8.5 — 15 Factores)
                        snapshot = orchestrator.tick_auditor.compute_metrics(symbol)
                        
                        # Preparar auditoría para el vector de 15 dimensiones
                        audit_data = {
                            'speed': snapshot.rejection_speed,
                            'vol_delta': snapshot.volume_delta,
                            'regime': snapshot.regime,
                        }
                        
                        # Obtener datos del otro símbolo para cross-asset
                        other_data = None
                        other_sym = "GOLD" if symbol == "EURUSD" else "EURUSD"
                        try:
                            other_snapshot = orchestrator.tick_auditor.compute_metrics(other_sym)
                            other_data = {
                                'close': other_snapshot.price,
                                'speed': other_snapshot.rejection_speed,
                                'vol_delta': other_snapshot.volume_delta,
                            }
                        except Exception:
                            pass
                        
                        # Construir vector Alfa de 15 dimensiones
                        alpha_dict = get_alpha_vector_15d(df_h1, symbol, audit_data, other_data)
                        
                        # ─── [EXP-021] INFERENCIA VÍA DOCKER ───
                        docker_ok = False
                        try:
                            brain_client = BrainDockerClient()
                            estado, veto, razon, detalles = brain_client.evaluate(alpha_dict)
                            origen = detalles.get('processed_by', 'LOCAL_FALLBACK')
                            
                            if veto:
                                logger.warning(f"   🛡️ VETO DE DOCKER: {razon} | Origen: {origen}")
                                proba = 0.0
                                direction = "SHORT"
                                docker_ok = True
                            else:
                                proba = detalles.get('proba', 0.5)
                                direction = detalles.get('direction', 'LONG')
                                logger.info(f"   🧠 Docker {symbol}: {proba*100:.2f}% → {direction} (Estado: {estado}) | Origen: {origen}")
                                docker_ok = True
                        except Exception as e:
                            logger.warning(f"⚠️ Docker no disponible ({e}). Usando fallback local.")
                        
                        if not docker_ok:
                            if model_loader is None or not model_loader._loaded:
                                logger.error("❌ No hay modelos locales disponibles para fallback.")
                                proba = 0.0
                                direction = "SHORT"
                            else:
                                try:
                                    scaler_feature_names = model_loader.scaler.feature_names_in_
                                    X_list_15d = [alpha_dict.get(name, 0.0) for name in scaler_feature_names]
                                    X_15d = pd.DataFrame([X_list_15d], columns=scaler_feature_names)
                                    X_scaled_15d = model_loader.scaler.transform(X_15d)
                                    
                                    model_feature_names = model_loader.models[symbol].feature_names_in_
                                    X_scaled_df = pd.DataFrame(X_scaled_15d, columns=scaler_feature_names)
                                    
                                    regime_map = {
                                        'alpha_regime_high_vol': 'ALTA VOLATILIDAD',
                                        'alpha_regime_low_vol': 'BAJA VOLATILIDAD',
                                        'alpha_regime_normal': 'NEUTRO',
                                    }
                                    active_regime = 'NEUTRO'
                                    for col, regime_name in regime_map.items():
                                        if X_scaled_df[col].iloc[0] > 0.5:
                                            active_regime = regime_name
                                            break
                                    
                                    X_model_dict = {}
                                    for name in model_feature_names:
                                        if name == 'alpha_regime':
                                            if active_regime == 'ALTA VOLATILIDAD':
                                                X_model_dict[name] = X_scaled_df['alpha_regime_high_vol'].iloc[0]
                                            elif active_regime == 'BAJA VOLATILIDAD':
                                                X_model_dict[name] = X_scaled_df['alpha_regime_low_vol'].iloc[0]
                                            else:
                                                X_model_dict[name] = X_scaled_df['alpha_regime_normal'].iloc[0]
                                        else:
                                            X_model_dict[name] = X_scaled_df[name].iloc[0]
                                    
                                    X_model = pd.DataFrame([X_model_dict], columns=model_feature_names)
                                    model = model_loader.models[symbol]
                                    proba = model.predict_proba(X_model)[0][1]
                                    direction = "LONG" if proba > 0.5 else "SHORT"
                                    proba = max(proba, 1 - proba)
                                    logger.info(f"   ⚠️ Fallback local {symbol}: {proba*100:.2f}% → {direction}")
                                except Exception as e2:
                                    logger.error(f"❌ Fallback local también falló {symbol}: {e2}")
                                    features = build_features_from_ticks(symbol, snapshot)
                                    direction, proba = model_loader.predict(symbol, features)
                                    logger.info(f"   ⚠️ Fallback último recurso {symbol}: {direction} @ {proba:.2%}")
                        
                        # D. EJECUTAR LÓGICA SMC SQUAD (V8.5)
                        if not df_h1.empty:
                            audit_smc = {
                                'speed': snapshot.rejection_speed,
                                'vol_delta': snapshot.volume_delta,
                                'regime': snapshot.regime,
                                'atr': snapshot.current_atr,
                            }
                            squad_result = execute_squad_logic(symbol, df_h1, audit_smc)
                            
                            if squad_result['squad_attack'] or squad_result['squad_trend']:
                                state[symbol]['squad'] = squad_result
                                logger.info(f"   ⚔️ SQUAD MODE ACTIVO en {symbol}")
                            else:
                                state[symbol]['squad'] = None
                        
                        # E. Calcular SL/TP basado en ATR
                        atr = snapshot.current_atr
                        if symbol == "GOLD":
                            sl_distance = atr * 1.5
                            tp_distance = atr * 3.0
                        else:
                            sl_distance = atr * 2.0
                            tp_distance = atr * 4.0
                        
                        entry_price = ask if direction == "LONG" else bid
                        sl_price = entry_price - sl_distance if direction == "LONG" else entry_price + sl_distance
                        tp_price = entry_price + tp_distance if direction == "LONG" else entry_price - tp_distance
                        
                        # ─── [FASE 10] PASAR POR META-BRAIN V10.3 ───
                        if proba >= 0.55:
                            if proba >= 0.85:
                                confidence = "ALTA"
                            else:
                                confidence = "MEDIA"
                            
                            SniperSignal_local = SniperSignal(
                                symbol=symbol,
                                direction=direction,
                                proba=proba,
                                confidence=confidence,
                                entry_price=entry_price,
                                sl_price=sl_price,
                                tp_price=tp_price,
                            )
                            logger.info(f"   🎯 Señal Sniper creada: {symbol} {direction} @ {proba*100:.1f}%")
                            
                            # ─── CONSULTAR AL META-BRAIN ───
                            signal = SniperSignal_local
                            
                            # 1. Actualizar estado del sistema en Meta-Brain
                            council_status = orchestrator.get_war_room_status()
                            meta_brain.update_system_state(
                                win_rate_24h=council_status['council'].get('daily_pnl', 0) / max(council_status['council'].get('total_approved', 1), 1),
                                drawdown=abs(min(0, council_status['council'].get('daily_pnl', 0))) / 10000,
                                consecutive_losses=council_status['council'].get('consecutive_losses', 0),
                                latency=0.05,
                                brain_confidence=proba,
                            )
                            
                            # 2. Obtener decisión del Meta-Brain
                            decision = meta_brain.evaluate(
                                symbol=symbol,
                                proba=proba,
                                atr=atr,
                                regime=snapshot.regime,
                                session="NY" if (13 <= now_utc.hour <= 20) else "LONDON" if (7 <= now_utc.hour <= 12) else "ASIA",
                                trend_strength=abs(alpha_dict.get('alpha_mom_6h', 0)),
                                cross_asset_alignment=abs(alpha_dict.get('alpha_divergence', 0)),
                            )
                            
                            # 3. Aplicar ajustes del Meta-Brain
                            if decision.should_trade:
                                logger.info(f"   ✅ Meta-Brain aprueba: utilidad={decision.utility_score:.4f} > umbral={decision.threshold:.4f}")
                                logger.info(f"   📊 Mercado: {decision.details.get('market_state', 'UNKNOWN')} | Sistema: {decision.details.get('system_alert', 'UNKNOWN')}")
                                logger.info(f"   🔧 Confianza={decision.adjusted_confidence:.2f} | Riesgo={decision.adjusted_risk_pct*100:.2f}% | SL={decision.adjusted_sl_atr:.1f}ATR | TP={decision.adjusted_tp_atr:.1f}ATR")
                                
                                # Recalcular SL/TP con ajustes del Meta-Brain
                                adjusted_sl = entry_price - (atr * decision.adjusted_sl_atr) if direction == "LONG" else entry_price + (atr * decision.adjusted_sl_atr)
                                adjusted_tp = entry_price + (atr * decision.adjusted_tp_atr) if direction == "LONG" else entry_price - (atr * decision.adjusted_tp_atr)
                                
                                # Crear señal con ajustes del Meta-Brain
                                adjusted_signal = SniperSignal(
                                    symbol=symbol,
                                    direction=direction,
                                    proba=proba,
                                    confidence=confidence,
                                    entry_price=entry_price,
                                    sl_price=adjusted_sl,
                                    tp_price=adjusted_tp,
                                )
                                
                                # PASAR POR EL CONSEJO DE CENTINELAS
                                logger.info(f"   🛡️ Consultando al Consejo de Centinelas...")
                                order = orchestrator.process_signal(adjusted_signal)
                                
                                # Actualizar estado para los mapas
                                state[symbol]['p'] = proba
                                state[symbol]['dir'] = 1 if direction == "LONG" else -1
                                state[symbol]['atr'] = atr
                                
                                if order:
                                    state[symbol]['verdict'] = "APROBADO"
                                    state[symbol]['reason'] = f"Meta-Brain utilidad={decision.utility_score:.3f}"
                                    logger.info(f"   🔥 ORDEN APROBADA POR CONSEJO + META-BRAIN: {symbol}")
                                    
                                    # ENVIAR ORDEN A MT5
                                    if mt5_connected:
                                        success = mt5_conn.send_order(order)
                                        if success:
                                            logger.info(f"   ✅ Orden enviada a MT5: {symbol} {direction}")
                                        else:
                                            logger.error(f"   ❌ Fallo al enviar orden a MT5")
                                    else:
                                        logger.info(f"   📝 [SIMULACIÓN] Orden lista: {symbol} {direction} {order.volume_lots} lots")
                                else:
                                    # Veto del Consejo - verificar bypass de alta confianza
                                    veto_reason = council_status.get('veto_profile', {}).get('last_veto_reason', 'Veto del Consejo')
                                    
                                    if proba >= 0.90:
                                        logger.info(f"   ⚡ BYPASS DE CONFIANZA: IA {proba*100:.1f}% sobrepasa veto del Consejo ({veto_reason}).")
                                        state[symbol]['verdict'] = "APROBADO (BYPASS)"
                                        state[symbol]['reason'] = f"Bypass Meta-Brain ({proba*100:.1f}%)"
                                        
                                        if mt5_connected:
                                            bypass_order = orchestrator.process_signal(adjusted_signal)
                                            if bypass_order:
                                                success = mt5_conn.send_order(bypass_order)
                                                if success:
                                                    logger.info(f"   ✅ BYPASS: Orden enviada a MT5: {symbol} {direction}")
                                                else:
                                                    logger.error(f"   ❌ BYPASS: Fallo al enviar orden a MT5")
                                            else:
                                                logger.info(f"   📝 [SIMULACIÓN BYPASS] Orden lista: {symbol} {direction}")
                                        else:
                                            logger.info(f"   📝 [SIMULACIÓN BYPASS] Orden lista: {symbol} {direction}")
                                    else:
                                        state[symbol]['verdict'] = "VETADO"
                                        state[symbol]['reason'] = veto_reason
                                        logger.info(f"   🛡️ SEÑAL VETADA EN {symbol}: {veto_reason}")
                                        
                                        # Registrar veto en Meta-Brain
                                        meta_brain.record_result(
                                            symbol=symbol,
                                            pnl=0,
                                            r_multiple=0,
                                            market_state=decision.details.get('market_state', 'UNKNOWN'),
                                            was_vetoed=True,
                                        )
                            else:
                                # Meta-Brain veta
                                state[symbol]['verdict'] = "VETADO (META-BRAIN)"
                                state[symbol]['reason'] = f"Utilidad={decision.utility_score:.3f} ≤ umbral={decision.threshold:.3f}"
                                logger.warning(f"   🧬 META-BRAIN VETA: utilidad={decision.utility_score:.4f} ≤ umbral={decision.threshold:.4f}")
                                logger.warning(f"   📊 Mercado: {decision.details.get('market_state', 'UNKNOWN')} | Sistema: {decision.details.get('system_alert', 'UNKNOWN')}")
                                
                                meta_brain.record_result(
                                    symbol=symbol,
                                    pnl=0,
                                    r_multiple=0,
                                    market_state=decision.details.get('market_state', 'UNKNOWN'),
                                    was_vetoed=True,
                                )
                        else:
                            # No hay señal - confianza por debajo del umbral
                            logger.info(f"   ⏭️ {symbol}: Sin señal (proba={proba*100:.1f}% < 55%)")
                            state[symbol]['p'] = proba
                            state[symbol]['dir'] = 1 if direction == "LONG" else -1
                            state[symbol]['atr'] = atr
                            state[symbol]['verdict'] = "SIN SEÑAL"
                            state[symbol]['reason'] = f"Confianza insuficiente ({proba*100:.1f}%)"
                    
                    except Exception as e:
                        logger.error(f"❌ Error procesando {symbol}: {e}")
                        import traceback
                        logger.error(traceback.format_exc())
                        continue
                
                last_hour = now_utc.hour
                
                # Exportar auditoría después de cada ciclo
                orchestrator.export_audit_log(AUDIT_LOG_PATH)
                
                # Mostrar resumen del Meta-Brain
                mb_perf = meta_brain.get_performance_summary()
                logger.info(f"PERF RAW = {mb_perf}")  # DEBUG: verificar claves exactas
                win_rate = mb_perf.get('win_rate', mb_perf.get('global_win_rate', 0))
                avg_r = mb_perf.get('avg_r', mb_perf.get('avg_r_multiple', 0))
                logger.info(f"\n📊 Meta-Brain V10.3 Performance:")
                logger.info(f"   Trades: {mb_perf.get('total_trades', 0)} | Win Rate: {win_rate*100:.1f}% | Avg R: {avg_r:.2f}")
                logger.info(f"   Expectancy: {mb_perf.get('expectancy', 0):.3f} | Profit Factor: {mb_perf.get('profit_factor', 0):.2f}")
                logger.info(f"   Vetoes: {mb_perf.get('total_vetoes', 0)} | Drawdown: {mb_perf.get('max_drawdown', 0)*100:.1f}%")
            
            # ─── CADA 30 SEGUNDOS: ACTUALIZAR MAPAS DE GUERRA ───
            if now_utc.second % 30 == 0 and now_utc.second != last_update_second:
                for symbol in SYMBOL_LIST:
                    output_path = f"logs/war_room_{symbol.lower()}.html"
                    update_war_map(symbol, mt5_conn, orchestrator, state, output_path)
                
                # Log de estado
                verdict_icons = {"APROBADO": "✅", "VETADO": "🛡️", "INIT": "⚪", "VETADO (META-BRAIN)": "🧬", "APROBADO (BYPASS)": "⚡"}
                status_parts = []
                for sym in SYMBOL_LIST:
                    s = state[sym]
                    icon = verdict_icons.get(s['verdict'], '⚪')
                    proba_str = f"{s['p']*100:.1f}%" if s['p'] > 0 else "—"
                    status_parts.append(f"{sym}: {icon} {s['verdict']} @ {proba_str}")
                
                uptime = int((datetime.now(timezone.utc) - start_time).total_seconds() / 60)
                logger.info(
                    f"🕒 [{now_lima.strftime('%H:%M')} Lima] "
                    f"Mapas actualizados | {' | '.join(status_parts)} | "
                    f"Uptime: {uptime}m"
                )
                
                last_update_second = now_utc.second
            
            # Pequeña pausa para no saturar CPU
            time.sleep(0.5)
    
    except KeyboardInterrupt:
        logger.info(f"\n{'=' * 70}")
        logger.info("🛑 STRATUM V8.5 DETENIDO POR EL USUARIO")
        logger.info(f"{'=' * 70}")
    
    except Exception as e:
        logger.error(f"❌ Error fatal en el bucle principal: {e}")
        import traceback
        logger.error(traceback.format_exc())
    
    finally:
        # ─── 4. SHUTDOWN GRACEFUL ───
        logger.info("\n🔄 Cerrando sistema ordenadamente...")
        
        # Exportar auditoría final
        try:
            orchestrator.export_audit_log(AUDIT_LOG_PATH)
        except NameError:
            logger.warning("⚠️ Orchestrator no inicializado, auditoría no disponible")
        except Exception as e:
            logger.warning(f"⚠️ Error exportando auditoría: {e}")
        
        # Guardar estado del Meta-Brain
        try:
            meta_brain.save_state("data/meta_brain_state.json")
            logger.info("💾 Estado del Meta-Brain guardado")
        except NameError:
            logger.warning("⚠️ Meta-Brain no inicializado, estado no guardado")
        except Exception as e:
            logger.warning(f"⚠️ No se pudo guardar estado del Meta-Brain: {e}")
        
        # Mostrar resumen final
        try:
            logger.info(orchestrator.summary())
        except NameError:
            logger.warning("⚠️ Orchestrator no inicializado, resumen no disponible")
        except Exception as e:
            logger.warning(f"⚠️ Error mostrando resumen: {e}")
        
        # Mostrar resumen del Meta-Brain (con protección si no se inicializó)
        try:
            mb_perf = meta_brain.get_performance_summary()
            win_rate = mb_perf.get('win_rate', mb_perf.get('global_win_rate', 0))
            avg_r = mb_perf.get('avg_r', mb_perf.get('avg_r_multiple', 0))
            logger.info(f"\n📊 Meta-Brain V10.3 — Resumen Final:")
            logger.info(f"   Trades ejecutados: {mb_perf.get('total_trades', 0)}")
            logger.info(f"   Win Rate: {win_rate*100:.1f}%")
            logger.info(f"   Avg R: {avg_r:.2f}")
            logger.info(f"   Expectancy: {mb_perf.get('expectancy', 0):.3f}")
            logger.info(f"   Profit Factor: {mb_perf.get('profit_factor', 0):.2f}")
            logger.info(f"   Vetoes: {mb_perf.get('total_vetoes', 0)}")
            logger.info(f"   Max Drawdown: {mb_perf.get('max_drawdown', 0)*100:.1f}%")
        except NameError:
            logger.info(f"\n📊 Meta-Brain V10.3 — No inicializado (error previo)")
        except Exception as e:
            logger.warning(f"⚠️ Error al obtener resumen del Meta-Brain: {e}")
        
        # Cerrar MT5
        mt5_conn.shutdown()
        
        logger.info("👋 STRATUM NEXUS V8.5 FINALIZADO")
        logger.info(f"   Tiempo total: {(datetime.now(timezone.utc) - start_time).total_seconds() / 60:.1f} minutos")
        logger.info(f"   Mapas: logs/war_room_eurusd.html, logs/war_room_gold.html")
        logger.info(f"   Auditoría: {AUDIT_LOG_PATH}")
        logger.info(f"   Meta-Brain: data/meta_brain_state.json")


if __name__ == "__main__":
    main()

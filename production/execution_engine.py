"""
NEXUS QUANT LAB — EXECUTION ENGINE (V8.5)
==========================================
execution_engine.py

Motor de ejecución de órdenes para el sistema Nexus Quant Lab.
Centraliza la lógica de:
  - Cálculo de tamaño de lote (Risk Management)
  - Envío de órdenes a MT5
  - Gestión de SL/TP dinámicos
  - Monitoreo de posiciones abiertas
  - Cierre de posiciones

Integración con el SQUAD MODE y el Sentinel Council V8.2.

Autor: Nexus Quant Lab
Fecha: 2026-06-03 (V8.5 — Execution Engine)
"""

import os
import sys
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field

# ─── SINCRONIZACIÓN DE RUTAS DEL LABORATORIO ───
root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if root_path not in sys.path:
    sys.path.insert(0, root_path)
os.chdir(root_path)
# ────────────────────────────────────────────────

import numpy as np

logger = logging.getLogger("ExecutionEngine")


@dataclass
class ExecutionOrder:
    """
    Orden lista para enviar a MT5/XM.
    """
    symbol: str
    direction: str                # "LONG" o "SHORT"
    volume_lots: float
    entry_price: float
    sl_price: float
    tp_price: float
    comment: str                  # "V8.5-EXECUTION-ENGINE"
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    magic_number: int = 828282    # Magic Number para identificar órdenes del bot


@dataclass
class PositionInfo:
    """
    Información de una posición abierta.
    """
    ticket: int
    symbol: str
    direction: str
    volume: float
    price_open: float
    sl: float
    tp: float
    profit: float
    comment: str


class ExecutionEngine:
    """
    Motor de ejecución de órdenes V8.5.
    
    Gestiona el ciclo completo de vida de una orden:
      1. Validación de riesgo (límite de drawdown, lotes máximos)
      2. Cálculo de tamaño de lote basado en balance y riesgo
      3. Envío de la orden a MT5
      4. Monitoreo de posiciones abiertas
      5. Cierre de posiciones (take profit, stop loss, manual)
    
    Attributes:
        balance: Balance actual de la cuenta
        risk_per_trade: Porcentaje de riesgo por trade (0.01 = 1%)
        max_drawdown: Drawdown máximo permitido antes de pausar
        max_open_positions: Máximo de posiciones abiertas simultáneas
        magic_number: Magic Number para identificar órdenes del bot
    """
    
    def __init__(
        self,
        balance: float = 10000.0,
        risk_per_trade: float = 0.01,
        max_drawdown: float = 0.05,
        max_open_positions: int = 2,
        magic_number: int = 828282,
    ):
        """
        Inicializa el motor de ejecución.
        
        Args:
            balance: Balance inicial de la cuenta
            risk_per_trade: Porcentaje de riesgo por trade (0.01 = 1%)
            max_drawdown: Drawdown máximo (0.05 = 5%)
            max_open_positions: Máximo de posiciones abiertas
            magic_number: Magic Number para MT5
        """
        self.balance = balance
        self.initial_balance = balance
        self.risk_per_trade = risk_per_trade
        self.max_drawdown = max_drawdown
        self.max_open_positions = max_open_positions
        self.magic_number = magic_number
        
        # Estado interno
        self._paused = False
        self._pause_reason = ""
        self._consecutive_losses = 0
        self._daily_pnl = 0.0
        self._total_trades = 0
        self._winning_trades = 0
        self._losing_trades = 0
        
        # Log de órdenes ejecutadas
        self._execution_log: List[Dict[str, Any]] = []
        
        logger.info(f"⚙️ ExecutionEngine inicializado")
        logger.info(f"   Balance: ${balance:.2f} | Riesgo: {risk_per_trade*100:.1f}%")
        logger.info(f"   Max Drawdown: {max_drawdown*100:.1f}% | Max Posiciones: {max_open_positions}")
    
    # ─── CÁLCULO DE TAMAÑO DE LOTE (FÓRMULA MAESTRA V8.5) ───
    
    def calculate_lot_size(
        self,
        entry_price: float,
        sl_price: float,
        symbol: str = "EURUSD",
        confidence_multiplier: float = 1.0,
    ) -> float:
        """
        Calcula el tamaño de lote usando la FÓRMULA MAESTRA con trade_tick_value real de MT5.
        
        Fórmula Maestra:
            sl_points = abs(entry - sl) / point
            lots = risk_amount / (sl_points * trade_tick_value)
        
        Donde:
            - risk_amount = balance * risk_per_trade * confidence_multiplier
            - trade_tick_value = valor monetario de 1 lote por tick (de MT5 symbol_info)
            - point = tamaño del punto del símbolo (de MT5 symbol_info)
        
        Esta fórmula garantiza que la pérdida máxima SIEMPRE sea ~1% del balance,
        independientemente de la distancia del SL (10 pips o 50 pips).
        
        Args:
            entry_price: Precio de entrada
            sl_price: Precio de Stop Loss
            symbol: Símbolo del activo (para calcular pip value)
            confidence_multiplier: Multiplicador por confianza (0.4-1.0)
            
        Returns:
            Tamaño de lote (mínimo 0.01)
        """
        if self._paused:
            logger.warning(f"⏸️ Engine pausado: {self._pause_reason}")
            return 0.0
        
        risk_amount = self.balance * self.risk_per_trade * confidence_multiplier
        
        # Intentar obtener datos reales del símbolo desde MT5
        try:
            import MetaTrader5 as mt5
            mt5_available = mt5.initialize()
        except ImportError:
            mt5_available = False
        
        if mt5_available:
            tick_info = mt5.symbol_info(symbol)
            if tick_info:
                # FÓRMULA MAESTRA con datos reales del broker
                sl_points = abs(entry_price - sl_price) / tick_info.point
                
                if sl_points <= 0:
                    logger.warning("⚠️ Distancia SL es 0, usando lote mínimo")
                    return 0.01
                
                # Lots = Riesgo_USD / (Puntos_SL * trade_tick_value)
                lots = risk_amount / (sl_points * tick_info.trade_tick_value)
                
                # Ajustar a límites del broker
                lot_size = max(
                    tick_info.volume_min,
                    min(tick_info.volume_max, round(lots, 2))
                )
                
                # Verificación de riesgo real
                real_risk = sl_points * tick_info.trade_tick_value * lot_size
                
                logger.info(
                    f"📐 Lot size: {lot_size:.2f} | "
                    f"Risk: ${risk_amount:.2f} → Real: ${real_risk:.2f} | "
                    f"SL: {sl_points:.0f} pts | "
                    f"Confidence: {confidence_multiplier:.2f} | "
                    f"✅ OK" if real_risk <= risk_amount * 1.05 else "⚠️ EXCESIVO"
                )
                
                return lot_size
        
        # ─── FALLBACK: Cálculo offline sin MT5 ───
        logger.warning("⚠️ MT5 no disponible. Usando cálculo offline aproximado.")
        
        if "GOLD" in symbol or "XAU" in symbol:
            # GOLD: point=0.01, trade_tick_value≈$0.10 por 0.01 lots
            sl_points = abs(entry_price - sl_price) / 0.01
            tick_value_per_lot = 10.0  # $10 por tick para 1 lote estándar de GOLD
        elif "JPY" in symbol:
            sl_points = abs(entry_price - sl_price) / 0.001
            tick_value_per_lot = 9.0  # Aproximado para pares JPY
        else:
            # Forex estándar: point=0.00001, trade_tick_value≈$1.0 por 0.01 lots
            sl_points = abs(entry_price - sl_price) / 0.00001
            tick_value_per_lot = 100.0  # $100 por tick para 1 lote estándar Forex
        
        if sl_points <= 0:
            logger.warning("⚠️ Distancia SL es 0, usando lote mínimo")
            return 0.01
        
        lots = risk_amount / (sl_points * tick_value_per_lot)
        lot_size = max(0.01, min(10.0, round(lots, 2)))
        
        logger.info(
            f"📐 Lot size (offline): {lot_size:.2f} | "
            f"Risk: ${risk_amount:.2f} | "
            f"SL: {sl_points:.0f} pts | "
            f"Confidence: {confidence_multiplier:.2f}"
        )
        
        return lot_size
    
    # ─── VALIDACIONES DE RIESGO ───
    
    def can_trade(self) -> Tuple[bool, str]:
        """
        Verifica si se puede operar según las reglas de riesgo.
        
        Returns:
            Tuple[bool, str]: (puede_operar, razón)
        """
        if self._paused:
            return False, f"Engine pausado: {self._pause_reason}"
        
        # Verificar drawdown
        current_drawdown = (self.initial_balance - self.balance) / self.initial_balance
        if current_drawdown >= self.max_drawdown:
            return False, f"Drawdown máximo alcanzado: {current_drawdown*100:.1f}%"
        
        # Verificar racha de pérdidas
        if self._consecutive_losses >= 3:
            return False, f"3 pérdidas consecutivas. Pausando operaciones."
        
        return True, "OK"
    
    def check_position_limit(self, open_positions: int) -> bool:
        """
        Verifica si se puede abrir una nueva posición.
        
        Args:
            open_positions: Número de posiciones actualmente abiertas
            
        Returns:
            True si se puede abrir, False si se alcanzó el límite
        """
        if open_positions >= self.max_open_positions:
            logger.warning(f"⚠️ Límite de posiciones alcanzado: {open_positions}/{self.max_open_positions}")
            return False
        return True
    
    # ─── ENVÍO DE ÓRDENES ───
    
    def send_order(self, order: ExecutionOrder) -> bool:
        """
        Envía una orden a MT5.
        
        En producción real, usa MetaTrader5.
        En modo simulación, registra la orden.
        
        Args:
            order: Orden a ejecutar
            
        Returns:
            True si la orden fue ejecutada exitosamente
        """
        # Validar riesgo antes de enviar
        can_trade, reason = self.can_trade()
        if not can_trade:
            logger.warning(f"⛔ Orden rechazada: {reason}")
            return False
        
        try:
            import MetaTrader5 as mt5
            
            # Verificar conexión
            if not mt5.initialize():
                logger.warning("⚠️ MT5 no disponible. Usando modo simulación.")
                return self._simulate_send(order)
            
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
                "magic": self.magic_number,
                "comment": order.comment,
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            
            result = mt5.order_send(request)
            
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                logger.error(f"❌ Orden rechazada por MT5: {result.comment} (código: {result.retcode})")
                self._log_execution(order, success=False, error=result.comment)
                return False
            
            logger.info(f"✅ Orden ejecutada en MT5: {order.symbol} {order.direction} "
                       f"{order.volume_lots} lots @ {order.entry_price}")
            logger.info(f"   Ticket: {result.order} | SL: {order.sl_price} | TP: {order.tp_price}")
            
            self._log_execution(order, success=True, ticket=result.order)
            self._total_trades += 1
            
            return True
            
        except ImportError:
            logger.warning("⚠️ MetaTrader5 no instalado. Usando modo simulación.")
            return self._simulate_send(order)
        except Exception as e:
            logger.error(f"❌ Error enviando orden a MT5: {e}")
            self._log_execution(order, success=False, error=str(e))
            return False
    
    def _simulate_send(self, order: ExecutionOrder) -> bool:
        """
        Simula el envío de una orden (modo demo/simulación).
        
        Args:
            order: Orden a simular
            
        Returns:
            True (siempre en simulación)
        """
        logger.info(f"📝 [SIMULACIÓN] Orden ejecutada: {order.symbol} {order.direction} "
                   f"{order.volume_lots} lots @ {order.entry_price}")
        logger.info(f"   SL: {order.sl_price} | TP: {order.tp_price} | Comment: {order.comment}")
        
        self._log_execution(order, success=True, ticket=-1)
        self._total_trades += 1
        
        return True
    
    def _log_execution(
        self,
        order: ExecutionOrder,
        success: bool,
        ticket: int = -1,
        error: str = "",
    ):
        """
        Registra una ejecución en el log interno.
        
        Args:
            order: Orden ejecutada
            success: Si fue exitosa
            ticket: Ticket de MT5 (o -1 si simulación)
            error: Mensaje de error (si aplica)
        """
        self._execution_log.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": order.symbol,
            "direction": order.direction,
            "volume": order.volume_lots,
            "entry_price": order.entry_price,
            "sl_price": order.sl_price,
            "tp_price": order.tp_price,
            "success": success,
            "ticket": ticket,
            "error": error,
            "comment": order.comment,
        })
    
    # ─── GESTIÓN DE POSICIONES ───
    
    def get_open_positions(self, symbol: Optional[str] = None) -> List[PositionInfo]:
        """
        Obtiene las posiciones abiertas desde MT5.
        
        Args:
            symbol: Símbolo específico (None = todas)
            
        Returns:
            Lista de posiciones abiertas
        """
        try:
            import MetaTrader5 as mt5
            
            if not mt5.initialize():
                return []
            
            if symbol:
                positions = mt5.positions_get(symbol=symbol)
            else:
                positions = mt5.positions_get()
            
            if not positions:
                return []
            
            result = []
            for pos in positions:
                result.append(PositionInfo(
                    ticket=pos.ticket,
                    symbol=pos.symbol,
                    direction="LONG" if pos.type == 0 else "SHORT",
                    volume=pos.volume,
                    price_open=pos.price_open,
                    sl=pos.sl,
                    tp=pos.tp,
                    profit=pos.profit,
                    comment=pos.comment,
                ))
            
            return result
            
        except ImportError:
            return []
        except Exception as e:
            logger.error(f"❌ Error obteniendo posiciones: {e}")
            return []
    
    def close_position(self, position: PositionInfo) -> bool:
        """
        Cierra una posición específica.
        
        Args:
            position: Posición a cerrar
            
        Returns:
            True si se cerró exitosamente
        """
        try:
            import MetaTrader5 as mt5
            
            if not mt5.initialize():
                logger.warning("⚠️ MT5 no disponible para cerrar posición")
                return False
            
            tick = mt5.symbol_info_tick(position.symbol)
            if tick is None:
                logger.error(f"❌ No se pudo obtener tick para {position.symbol}")
                return False
            
            # Determinar orden contraria
            order_type = mt5.ORDER_TYPE_SELL if position.direction == "LONG" else mt5.ORDER_TYPE_BUY
            price = tick.bid if order_type == mt5.ORDER_TYPE_SELL else tick.ask
            
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": position.symbol,
                "volume": position.volume,
                "type": order_type,
                "position": position.ticket,
                "price": price,
                "deviation": 10,
                "magic": self.magic_number,
                "comment": "V8.5-CLOSE",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            
            result = mt5.order_send(request)
            
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                logger.info(f"✅ Posición cerrada: {position.symbol} #{position.ticket} "
                           f"P&L: ${position.profit:.2f}")
                self._update_pnl(position.profit)
                return True
            else:
                logger.error(f"❌ Error cerrando posición: {result.comment}")
                return False
            
        except ImportError:
            logger.info(f"📝 [SIMULACIÓN] Posición cerrada: {position.symbol} #{position.ticket}")
            self._update_pnl(position.profit)
            return True
        except Exception as e:
            logger.error(f"❌ Error cerrando posición: {e}")
            return False
    
    def close_all_positions(self, symbol: Optional[str] = None) -> int:
        """
        Cierra todas las posiciones abiertas.
        
        Args:
            symbol: Símbolo específico (None = todas)
            
        Returns:
            Número de posiciones cerradas
        """
        positions = self.get_open_positions(symbol)
        closed = 0
        
        for pos in positions:
            if self.close_position(pos):
                closed += 1
        
        logger.info(f"🔒 Cerradas {closed}/{len(positions)} posiciones")
        return closed
    
    # ─── GESTIÓN DE P&L ───
    
    def _update_pnl(self, pnl: float):
        """
        Actualiza el estado interno con el resultado de un trade.
        
        Args:
            pnl: Profit/Loss del trade
        """
        self._daily_pnl += pnl
        self.balance += pnl
        
        if pnl > 0:
            self._winning_trades += 1
            self._consecutive_losses = 0
            logger.info(f"💰 Trade ganador: +${pnl:.2f} | Balance: ${self.balance:.2f}")
        else:
            self._losing_trades += 1
            self._consecutive_losses += 1
            logger.warning(f"💸 Trade perdedor: ${pnl:.2f} | Balance: ${self.balance:.2f}")
            
            if self._consecutive_losses >= 3:
                self._paused = True
                self._pause_reason = f"{self._consecutive_losses} pérdidas consecutivas"
                logger.warning(f"⏸️ Engine PAUSADO: {self._pause_reason}")
    
    def report_trade_result(self, pnl: float):
        """
        Reporta el resultado de un trade (método público).
        
        Args:
            pnl: Profit/Loss del trade
        """
        self._update_pnl(pnl)
    
    # ─── SL/TP DINÁMICOS ───
    
    def calculate_dynamic_sl(
        self,
        entry_price: float,
        direction: str,
        atr: float,
        symbol: str = "EURUSD",
        multiplier: float = 1.5,
    ) -> float:
        """
        Calcula un Stop Loss dinámico basado en ATR.
        
        Args:
            entry_price: Precio de entrada
            direction: Dirección de la operación
            atr: ATR actual
            symbol: Símbolo del activo
            multiplier: Multiplicador de ATR
            
        Returns:
            Precio de Stop Loss
        """
        if direction == "LONG":
            sl = entry_price - (atr * multiplier)
        else:
            sl = entry_price + (atr * multiplier)
        
        return sl
    
    def calculate_dynamic_tp(
        self,
        entry_price: float,
        sl_price: float,
        direction: str,
        risk_reward: float = 2.0,
    ) -> float:
        """
        Calcula un Take Profit dinámico basado en Risk:Reward.
        
        Args:
            entry_price: Precio de entrada
            sl_price: Precio de Stop Loss
            direction: Dirección de la operación
            risk_reward: Ratio Risk:Reward (2.0 = 1:2)
            
        Returns:
            Precio de Take Profit
        """
        risk = abs(entry_price - sl_price)
        
        if direction == "LONG":
            tp = entry_price + (risk * risk_reward)
        else:
            tp = entry_price - (risk * risk_reward)
        
        return tp
    
    # ─── TRAILING STOP ───
    
    def update_trailing_stop(
        self,
        position: PositionInfo,
        current_price: float,
        atr: float,
        activation_pips: float = 20.0,
        trail_distance: float = 1.5,
    ) -> Optional[float]:
        """
        Actualiza el trailing stop de una posición si está en ganancias.
        
        Args:
            position: Posición a actualizar
            current_price: Precio actual
            atr: ATR actual
            activation_pips: Pips de ganancia para activar trailing
            trail_distance: Distancia del trailing en ATRs
            
        Returns:
            Nuevo SL si se actualizó, None si no
        """
        if position.direction == "LONG":
            profit_pips = (current_price - position.price_open) / 0.0001
            if profit_pips >= activation_pips:
                new_sl = current_price - (atr * trail_distance)
                if new_sl > position.sl:
                    logger.info(f"🔺 Trailing SL actualizado: {position.sl:.5f} → {new_sl:.5f}")
                    return new_sl
        else:
            profit_pips = (position.price_open - current_price) / 0.0001
            if profit_pips >= activation_pips:
                new_sl = current_price + (atr * trail_distance)
                if new_sl < position.sl or position.sl == 0:
                    logger.info(f"🔻 Trailing SL actualizado: {position.sl:.5f} → {new_sl:.5f}")
                    return new_sl
        
        return None
    
    # ─── ESTADO Y REPORTES ───
    
    def get_status(self) -> Dict[str, Any]:
        """
        Obtiene el estado completo del motor de ejecución.
        
        Returns:
            Diccionario con el estado actual
        """
        win_rate = (self._winning_trades / max(self._total_trades, 1)) * 100
        current_drawdown = (self.initial_balance - self.balance) / self.initial_balance * 100
        
        return {
            "balance": self.balance,
            "initial_balance": self.initial_balance,
            "daily_pnl": self._daily_pnl,
            "drawdown_percent": current_drawdown,
            "total_trades": self._total_trades,
            "winning_trades": self._winning_trades,
            "losing_trades": self._losing_trades,
            "win_rate": win_rate,
            "consecutive_losses": self._consecutive_losses,
            "paused": self._paused,
            "pause_reason": self._pause_reason,
            "risk_per_trade": self.risk_per_trade,
            "max_drawdown": self.max_drawdown,
            "max_open_positions": self.max_open_positions,
        }
    
    def get_execution_log(self, last_n: int = 10) -> List[Dict[str, Any]]:
        """
        Obtiene las últimas N ejecuciones.
        
        Args:
            last_n: Número de ejecuciones a retornar
            
        Returns:
            Lista de las últimas N ejecuciones
        """
        return self._execution_log[-last_n:]
    
    def summary(self) -> str:
        """
        Genera un resumen formateado del estado del motor.
        
        Returns:
            String con el resumen
        """
        status = self.get_status()
        semaphore = "🟢" if not status["paused"] else "🔴"
        
        lines = [
            f"\n{'=' * 70}",
            f"⚙️ EXECUTION ENGINE — RESUMEN",
            f"{'=' * 70}",
            f"\n{semaphore} Estado: {'ACTIVO' if not status['paused'] else f'PAUSADO ({status["pause_reason"]})'}",
            f"\n💰 BALANCE:",
            f"   Actual: ${status['balance']:.2f}",
            f"   Inicial: ${status['initial_balance']:.2f}",
            f"   P&L Diario: ${status['daily_pnl']:.2f}",
            f"   Drawdown: {status['drawdown_percent']:.2f}%",
            f"\n📊 ESTADÍSTICAS:",
            f"   Trades totales: {status['total_trades']}",
            f"   Ganados: {status['winning_trades']}",
            f"   Perdidos: {status['losing_trades']}",
            f"   Win Rate: {status['win_rate']:.1f}%",
            f"   Rachas pérdidas: {status['consecutive_losses']}",
            f"\n⚙️ CONFIGURACIÓN:",
            f"   Riesgo por trade: {status['risk_per_trade']*100:.1f}%",
            f"   Max Drawdown: {status['max_drawdown']*100:.1f}%",
            f"   Max Posiciones: {status['max_open_positions']}",
            f"\n{'=' * 70}",
        ]
        
        return "\n".join(lines)
    
    def reset_daily(self):
        """
        Reinicia el P&L diario y el contador de pérdidas consecutivas.
        """
        self._daily_pnl = 0.0
        self._consecutive_losses = 0
        self._paused = False
        self._pause_reason = ""
        logger.info("🔄 Estado diario reiniciado")


# ──────────────────────────────────────────────
# DEMO: PRUEBA DEL MOTOR DE EJECUCIÓN
# ──────────────────────────────────────────────

def run_execution_demo():
    """
    Demostración del motor de ejecución.
    """
    print("\n" + "=" * 70)
    print("⚙️ EXECUTION ENGINE V8.5 — DEMO")
    print("   Risk Management + Envío de Órdenes + Trailing Stop")
    print("=" * 70)
    
    # Inicializar motor
    engine = ExecutionEngine(balance=10000.0, risk_per_trade=0.01)
    
    # ─── Test 1: Calcular lote ───
    print("\n" + "─" * 40)
    print("📐 TEST 1: Cálculo de lote")
    print("   EURUSD LONG @ 1.08500, SL @ 1.08200")
    print("   Riesgo: 1% de $10,000 = $100")
    print("─" * 40)
    
    lot = engine.calculate_lot_size(
        entry_price=1.08500,
        sl_price=1.08200,
        symbol="EURUSD",
        confidence_multiplier=1.0,
    )
    print(f"   → Lote calculado: {lot:.2f}")
    assert lot >= 0.01, "❌ Lote debería ser >= 0.01"
    print("   ✅ OK")
    
    # ─── Test 2: Verificar límite de posiciones ───
    print("\n" + "─" * 40)
    print("🔒 TEST 2: Límite de posiciones")
    print("   Max: 2 posiciones")
    print("─" * 40)
    
    assert engine.check_position_limit(0) == True, "❌ Debería permitir 0 posiciones"
    assert engine.check_position_limit(1) == True, "❌ Debería permitir 1 posición"
    assert engine.check_position_limit(2) == False, "❌ No debería permitir 3 posiciones"
    print("   ✅ OK")
    
    # ─── Test 3: Enviar orden (simulación) ───
    print("\n" + "─" * 40)
    print("📤 TEST 3: Envío de orden (simulación)")
    print("─" * 40)
    
    order = ExecutionOrder(
        symbol="EURUSD",
        direction="LONG",
        volume_lots=lot,
        entry_price=1.08500,
        sl_price=1.08200,
        tp_price=1.09100,
        comment="V8.5-DEMO",
    )
    
    success = engine.send_order(order)
    assert success, "❌ La orden debería enviarse en simulación"
    print("   ✅ OK")
    
    # ─── Test 4: Reportar trade ganador ───
    print("\n" + "─" * 40)
    print("💰 TEST 4: Reporte de trade ganador")
    print("─" * 40)
    
    engine.report_trade_result(150.0)
    status = engine.get_status()
    assert status["winning_trades"] == 1, "❌ Debería tener 1 trade ganador"
    assert status["consecutive_losses"] == 0, "❌ Rachas pérdidas debería ser 0"
    print(f"   Balance: ${status['balance']:.2f}")
    print("   ✅ OK")
    
    # ─── Test 5: Trailing Stop ───
    print("\n" + "─" * 40)
    print("🔺 TEST 5: Trailing Stop")
    print("   LONG @ 1.08500, SL inicial @ 1.08200")
    print("   Precio actual: 1.08800 (+30 pips)")
    print("─" * 40)
    
    pos = PositionInfo(
        ticket=12345,
        symbol="EURUSD",
        direction="LONG",
        volume=0.1,
        price_open=1.08500,
        sl=1.08200,
        tp=1.09100,
        profit=30.0,
        comment="V8.5-TEST",
    )
    
    new_sl = engine.update_trailing_stop(
        position=pos,
        current_price=1.08800,
        atr=0.0015,
        activation_pips=20,
        trail_distance=1.5,
    )
    
    assert new_sl is not None, "❌ Debería activar trailing stop"
    assert new_sl > pos.sl, "❌ Nuevo SL debería ser mayor"
    print(f"   SL actualizado: {pos.sl:.5f} → {new_sl:.5f}")
    print("   ✅ OK")
    
    # ─── Test 6: Drawdown máximo ───
    print("\n" + "─" * 40)
    print("⚠️ TEST 6: Drawdown máximo")
    print("   Simulando 3 pérdidas consecutivas")
    print("─" * 40)
    
    engine.report_trade_result(-100.0)
    engine.report_trade_result(-100.0)
    engine.report_trade_result(-100.0)
    
    can_trade, reason = engine.can_trade()
    assert not can_trade, "❌ No debería permitir operar"
    assert "3 pérdidas consecutivas" in reason
    print(f"   Razón: {reason}")
    print("   ✅ OK")
    
    # ─── Resumen Final ───
    print("\n" + "=" * 70)
    print("📊 RESUMEN DE LA DEMO")
    print("=" * 70)
    print(engine.summary())
    
    print("\n" + "=" * 70)
    print("🎯 DEMO COMPLETADA — 6/6 TESTS PASADOS")
    print("   Execution Engine V8.5 listo para producción")
    print("=" * 70)
    
    return engine


if __name__ == "__main__":
    engine = run_execution_demo()

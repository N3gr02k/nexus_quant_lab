"""
test_risk_engine.py — Validación de Riesgo V8.4
==============================================
Verifica que el motor de ejecución respeta el 1% de riesgo ($97.54)
en todos los escenarios: SL normal, micro-scalp, Turtle Soup Gold, alta volatilidad.
NO envía órdenes reales — solo imprime el cálculo de lotaje.
"""

import MetaTrader5 as mt5
import pandas as pd

# 1. Conexión
if not mt5.initialize():
    print("❌ Error conectando a MT5")
    quit()

# 2. Configuración de Test
balance = mt5.account_info().balance
risk_pct = 0.01
target_risk_usd = balance * risk_pct

print(f"📊 --- VALIDACIÓN DE RIESGO V8.4 ---")
print(f"💰 Balance Actual: ${balance:.2f}")
print(f"🎯 Riesgo Objetivo (1%): ${target_risk_usd:.2f}\n")

def validate_scenario(symbol, entry, sl, comment):
    tick_info = mt5.symbol_info(symbol)
    if not tick_info:
        print(f"❌ No se encontró info de {symbol}")
        return

    # Cálculo de puntos de SL
    sl_points = abs(entry - sl) / tick_info.point
    
    # FÓRMULA MAESTRA (MT5):
    # Lots = Riesgo_USD / (Puntos_SL * trade_tick_value)
    # trade_tick_value ya es el valor monetario por tick (movimiento mínimo)
    lots = target_risk_usd / (sl_points * tick_info.trade_tick_value)
    
    # Ajuste a límites del broker
    final_lots = max(tick_info.volume_min, min(tick_info.volume_max, round(lots, 2)))
    
    # Verificación de riesgo real
    real_risk = sl_points * tick_info.trade_tick_value * final_lots
    
    print(f"🔹 Escenario: {comment} ({symbol})")
    print(f"   Distancia SL: {sl_points:.0f} puntos")
    print(f"   Lotaje Calculado: {final_lots}")
    print(f"   Pérdida Real si toca SL: ${real_risk:.2f} " + ("✅ OK" if real_risk <= target_risk_usd * 1.05 else "⚠️ EXCESIVO"))
    print("-" * 40)

# --- ESCENARIOS DE PRUEBA ---

# Escenario A: EURUSD con SL normal (15 pips / 150 puntos)
validate_scenario("EURUSD", 1.16000, 1.15850, "Normal Sniper")

# Escenario B: EURUSD con SL ajustado (5 pips / 50 puntos)
validate_scenario("EURUSD", 1.16000, 1.15950, "Micro-Scalp")

# Escenario C: GOLD con SL institucional ($5.00 de distancia)
# En MT5 Gold, $5.00 suelen ser 500 puntos si el punto es 0.01
validate_scenario("GOLD", 2350.00, 2345.00, "Turtle Soup Gold")

# Escenario D: GOLD con SL volátil ($15.00 de distancia)
validate_scenario("GOLD", 2350.00, 2335.00, "High Volatility Gold")

mt5.shutdown()

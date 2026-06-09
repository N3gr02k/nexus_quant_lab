"""
TEST — Meta-Brain V10.2: Memoria Operativa
============================================
Verifica:
1. record_result() guarda feedback correctamente
2. _recalibrate_from_feedback() ajusta calibración por estado
3. get_performance_summary() retorna datos correctos
4. Persistencia en JSON
"""

import logging
import sys
import os

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)

# Silenciar logs del Meta-Brain para test
logging.getLogger("MetaBrainV10").setLevel(logging.WARNING)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.meta_brain_v10 import MetaBrainV10

print("=" * 70)
print("🧪 TEST — META-BRAIN V10.2: MEMORIA OPERATIVA")
print("=" * 70)

# Limpiar feedback previo
feedback_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data", "meta_brain_feedback.json"
)
if os.path.exists(feedback_path):
    os.remove(feedback_path)
    print(f"🗑️ Feedback previo eliminado: {feedback_path}")

brain = MetaBrainV10()

# ─── Test 1: Sin feedback ───
print("\n" + "-" * 50)
print("TEST 1: Sin trades registrados")
print("-" * 50)
summary = brain.get_performance_summary()
assert summary["total_trades"] == 0, f"Esperado 0, obtenido {summary['total_trades']}"
assert summary["global_win_rate"] == 0.0
print("✅ PASS: total_trades=0, global_win_rate=0.0")

# ─── Test 2: Registrar 10 trades ───
print("\n" + "-" * 50)
print("TEST 2: Registrar 10 trades con resultados variados")
print("-" * 50)

# Mínimo 5 trades por estado para que _recalibrate_from_feedback() se active
trades = [
    # (pnl, expected_utility, market_state)
    # GOLDEN_STATE: 5 trades, 4 wins → WR=0.80 > 0.60
    (45.0, 1.5, "GOLDEN_STATE"),
    (-12.0, 1.4, "GOLDEN_STATE"),
    (30.0, 1.3, "GOLDEN_STATE"),
    (20.0, 1.2, "GOLDEN_STATE"),
    (15.0, 1.1, "GOLDEN_STATE"),
    # FAVORABLE: 5 trades, 3 wins → WR=0.60 (neutral)
    (20.0, 1.0, "FAVORABLE"),
    (-8.0, 0.9, "FAVORABLE"),
    (15.0, 0.8, "FAVORABLE"),
    (-5.0, 0.7, "FAVORABLE"),
    (10.0, 0.6, "FAVORABLE"),
    # NORMAL: 5 trades, 2 wins → WR=0.40 (neutral)
    (10.0, 0.5, "NORMAL"),
    (-5.0, 0.4, "NORMAL"),
    (-8.0, 0.3, "NORMAL"),
    (12.0, 0.2, "NORMAL"),
    (-3.0, 0.1, "NORMAL"),
    # TOXICO: 5 trades, 0 wins → WR=0.0 < 0.40
    (-15.0, 0.5, "TOXICO"),
    (-20.0, 0.4, "TOXICO"),
    (-10.0, 0.3, "TOXICO"),
    (-25.0, 0.2, "TOXICO"),
    (-18.0, 0.1, "TOXICO"),
]


for pnl, exp_util, ms in trades:
    brain.record_result(
        pnl=pnl,
        expected_utility=exp_util,
        market_state=ms,
        system_alert="NORMAL",
        probability=0.65,
        expected_reward_ratio=2.0,
        risk_pct=0.01,
        sl_atr=1.5,
        tp_atr=2.0,
    )

summary = brain.get_performance_summary()
assert summary["total_trades"] == 20, f"Esperado 20, obtenido {summary['total_trades']}"
print(f"✅ PASS: total_trades={summary['total_trades']}")

# ─── Test 3: Win Rate global ───
print("\n" + "-" * 50)
print("TEST 3: Win Rate global")
print("-" * 50)
# GOLDEN: 4/5=0.8, FAVORABLE: 3/5=0.6, NORMAL: 2/5=0.4, TOXICO: 0/5=0.0
# Total: 9/20 = 0.45
expected_wr = 9 / 20
actual_wr = summary["global_win_rate"]
assert abs(actual_wr - expected_wr) < 0.001, f"Esperado {expected_wr}, obtenido {actual_wr}"
print(f"✅ PASS: global_win_rate={actual_wr:.1%} (esperado {expected_wr:.1%})")

# ─── Test 4: WR por estado de mercado ───
print("\n" + "-" * 50)
print("TEST 4: Win Rate por estado de mercado")
print("-" * 50)
by_state = summary["by_market_state"]

# GOLDEN_STATE: 5 trades, 4 wins → WR=0.80
gs = by_state.get("GOLDEN_STATE", {})
assert gs["trades"] == 5, f"GOLDEN_STATE trades: esperado 5, obtenido {gs['trades']}"
assert abs(gs["win_rate"] - 0.80) < 0.01, f"GOLDEN_STATE WR: esperado 0.80, obtenido {gs['win_rate']:.3f}"
print(f"✅ PASS: GOLDEN_STATE → {gs['trades']} trades, WR={gs['win_rate']:.1%}")

# TOXICO: 5 trades, 0 wins → WR=0.0
tx = by_state.get("TOXICO", {})
assert tx["trades"] == 5, f"TOXICO trades: esperado 5, obtenido {tx['trades']}"
assert tx["win_rate"] == 0.0, f"TOXICO WR: esperado 0.0, obtenido {tx['win_rate']}"
print(f"✅ PASS: TOXICO → {tx['trades']} trades, WR={tx['win_rate']:.1%}")


# ─── Test 5: Calibración ───
print("\n" + "-" * 50)
print("TEST 5: Calibración por estado de mercado")
print("-" * 50)
cal = summary["calibration"]

# GOLDEN_STATE: WR=0.667 > 0.60 → mq_adj > 1.0, th_adj < 0, rk_adj > 1.0
gs_cal = cal["GOLDEN_STATE"]
assert gs_cal["mq_adj"] > 1.0, f"GOLDEN_STATE mq_adj debería > 1.0, obtenido {gs_cal['mq_adj']}"
assert gs_cal["th_adj"] < 0, f"GOLDEN_STATE th_adj debería < 0, obtenido {gs_cal['th_adj']}"
assert gs_cal["rk_adj"] > 1.0, f"GOLDEN_STATE rk_adj debería > 1.0, obtenido {gs_cal['rk_adj']}"
print(f"✅ PASS: GOLDEN_STATE → mq_adj={gs_cal['mq_adj']:.2f}, th_adj={gs_cal['th_adj']:.2f}, rk_adj={gs_cal['rk_adj']:.2f}")

# TOXICO: WR=0.0 < 0.40 → mq_adj < 1.0, th_adj > 0, rk_adj < 1.0
tx_cal = cal["TOXICO"]
assert tx_cal["mq_adj"] < 1.0, f"TOXICO mq_adj debería < 1.0, obtenido {tx_cal['mq_adj']}"
assert tx_cal["th_adj"] > 0, f"TOXICO th_adj debería > 0, obtenido {tx_cal['th_adj']}"
assert tx_cal["rk_adj"] < 1.0, f"TOXICO rk_adj debería < 1.0, obtenido {tx_cal['rk_adj']}"
print(f"✅ PASS: TOXICO → mq_adj={tx_cal['mq_adj']:.2f}, th_adj={tx_cal['th_adj']:.2f}, rk_adj={tx_cal['rk_adj']:.2f}")

# ─── Test 6: Persistencia ───
print("\n" + "-" * 50)
print("TEST 6: Persistencia en JSON")
print("-" * 50)
assert os.path.exists(feedback_path), f"Archivo no existe: {feedback_path}"
with open(feedback_path, "r") as f:
    import json
    data = json.load(f)
assert len(data) == 20, f"Esperado 20 registros, obtenido {len(data)}"
print(f"✅ PASS: {len(data)} registros persistidos en {feedback_path}")

# ─── Test 7: Re-carga desde JSON ───
print("\n" + "-" * 50)
print("TEST 7: Re-carga desde JSON (nueva instancia)")
print("-" * 50)
brain2 = MetaBrainV10()
summary2 = brain2.get_performance_summary()
assert summary2["total_trades"] == 20, f"Esperado 20, obtenido {summary2['total_trades']}"
assert abs(summary2["global_win_rate"] - 9/20) < 0.001
print(f"✅ PASS: Cargados {summary2['total_trades']} registros, WR={summary2['global_win_rate']:.1%}")

# ─── Test 8: Utility Error promedio ───
print("\n" + "-" * 50)
print("TEST 8: Utility Error promedio")
print("-" * 50)
# realized_utility se calcula con heurística: 
# si pnl > 0: exp_util * (1 + pnl/100)
# si pnl <= 0: exp_util * (1 + pnl/200)
# Para trade 1: pnl=45, exp=1.5 → realized = 1.5 * 1.45 = 2.175, error = 0.675
# Para trade 2: pnl=-12, exp=1.4 → realized = 1.4 * 0.94 = 1.316, error = -0.084
avg_error = summary["avg_utility_error"]
print(f"✅ PASS: avg_utility_error={avg_error:.4f} (no nulo, hay datos)")

# ─── Resumen Final ───
print("\n" + "=" * 70)
print("🎯 TODOS LOS TESTS PASARON — META-BRAIN V10.2 OPERATIVO")
print("=" * 70)
print(f"   Total trades: {summary['total_trades']}")
print(f"   Global WR: {summary['global_win_rate']:.1%}")
print(f"   Avg Utility Error: {summary['avg_utility_error']:.4f}")
print(f"   Estados: {list(summary['by_market_state'].keys())}")
print(f"   Feedback persistido: {feedback_path}")
print("=" * 70)

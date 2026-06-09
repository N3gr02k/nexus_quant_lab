"""
TEST — Meta-Brain V10.3 (R-Multiple + Calibración Ponderada)
"""
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(name)s | %(levelname)s | %(message)s')
from core.meta_brain_v10 import MetaBrainV10

brain = MetaBrainV10()

# Simular 12 trades con R-multiple variado para probar V10.3
for i in range(12):
    if i < 4:
        ms = 'GOLDEN_STATE'
        pnl = 45.0 if i % 2 == 0 else -12.0
        r_mult = 3.5 if i % 2 == 0 else -0.8
    elif i < 8:
        ms = 'FAVORABLE'
        pnl = 30.0 if i % 2 == 0 else -8.0
        r_mult = 2.2 if i % 2 == 0 else -0.5
    else:
        ms = 'NORMAL'
        pnl = 10.0 if i % 2 == 0 else -5.0
        r_mult = 0.8 if i % 2 == 0 else -0.3
    
    brain.record_result(
        pnl=pnl,
        expected_utility=1.5 - i * 0.1,
        market_state=ms,
        system_alert='NORMAL',
        probability=0.65,
        expected_reward_ratio=2.0,
        risk_pct=0.01,
        sl_atr=1.5,
        tp_atr=2.0,
        r_multiple=r_mult,
    )

summary = brain.get_performance_summary()
print()
print('=' * 70)
print('📊 RESUMEN DE RENDIMIENTO — FASE 10.3 (R-Multiple)')
print('=' * 70)
print(f'Total trades: {summary["total_trades"]}')
print(f'Global WR: {summary["global_win_rate"]:.1%}')
print(f'Avg Utility Error: {summary["avg_utility_error"]:.4f}')
print()
print('WR por estado de mercado:')
for ms, data in summary['by_market_state'].items():
    print(f'  {ms}: {data["trades"]} trades, WR={data["win_rate"]:.1%}')
print()
print('Calibración actual (V10.3):')
for ms, cal in summary['calibration'].items():
    avg_r = cal.get('avg_r', 0.0)
    print(f'  {ms}: mq_adj={cal["mq_adj"]:.2f}, th_adj={cal["th_adj"]:.2f}, rk_adj={cal["rk_adj"]:.2f}, avg_R={avg_r:+.2f}')
print()
print('Últimos 3 trades:')
for r in summary['recent_trades'][:3]:
    print(f'  {r["timestamp"][:19]} | PNL=${r["pnl"]:+.2f} | R={r["r_multiple"]:+.2f} | ExpUtil={r["expected_utility"]:.3f} -> RealUtil={r["realized_utility"]:.3f} | {r["market_state"]}')
print('=' * 70)

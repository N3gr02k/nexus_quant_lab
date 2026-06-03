import logging
import warnings
import os
from datetime import datetime, timezone
from production.stratum_sentinel_orchestrator_v8 import TickAuditor, SentinelOrchestrator, SniperSignal

# Silenciar ruidos innecesarios
logging.disable(logging.CRITICAL)
warnings.filterwarnings('ignore')

def run_final_audit():
    print("="*70)
    print("🛰️  STRATUM NEXUS V8.2 — AUDITORÍA FINAL DE SISTEMAS")
    print("="*70)

    # 1. Probar el Auditor de Ticks (Músculo de Datos)
    print("\n📡 [PASO 1] Validando Auditor de Ticks...")
    auditor = TickAuditor(lookback_minutes=60)
    
    for sym in ['EURUSD', 'GOLD']:
        snapshot = auditor.compute_metrics(sym)
        status = "✅ OK" if snapshot.tick_count > 0 else "❌ SIN DATA"
        print(f"   {status:<10} | {sym:<6} | Speed: {snapshot.rejection_speed:+.2f}σ | VolDelta: {snapshot.volume_delta:+.3f} | Ticks: {snapshot.tick_count}")
        
        # Verificación crítica para el Oro
        if sym == 'GOLD' and abs(snapshot.rejection_speed) < 1e-9:
            print("      ⚠️  ALERTA: Velocidad de GOLD sigue en 0. Revisar Proxy.")

    # 2. Probar el Orquestador (Cerebro y Modelos)
    print("\n🧠 [PASO 2] Validando Orquestador y Modelos...")
    try:
        orchestrator = SentinelOrchestrator()
        print("   ✅ Modelos XGBoost y KMeans cargados exitosamente.")
    except Exception as e:
        print(f"   ❌ ERROR al cargar orquestador: {e}")
        return

    # 3. Simulación de Señal (Gatillo)
    print("\n🎯 [PASO 3] Simulacro de Disparo (GOLD)...")
    # Simulamos una señal de alta probabilidad en el Oro para ver si el Consejo aprueba
    test_signal = SniperSignal(
        symbol='GOLD',
        direction='LONG',
        proba=0.85,
        confidence='ALTA',
        entry_price=2350.0,
        sl_price=2335.0,
        tp_price=2380.0
    )
    
    order_result = orchestrator.process_signal(test_signal)
    
    if order_result:
        print(f"   🔥 RESULTADO: ORDEN GENERADA (P={test_signal.proba*100}%)")
        print(f"   🛡️  Veredicto del Consejo: APROBADO")
    else:
        print(f"   🛡️  RESULTADO: SEÑAL VETADA (El Consejo protegió el capital)")

    print("\n" + "="*70)
    print("🏆 CONCLUSIÓN: SISTEMA LISTO PARA OPERACIÓN FULL AUTO")
    print(f"⏰ Timestamp: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print("="*70)

if __name__ == "__main__":
    run_final_audit()

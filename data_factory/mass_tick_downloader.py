"""
NEXUS QUANT LAB — Fase 4: Data Muscle
========================================
mass_tick_downloader.py

DESCARGA MASIVA DE TICKS — Construyendo el músculo del Laboratorio.

¿Por qué?
  El dataset actual tiene ~76 muestras sincronizadas. Para que el
  Shadow Clustering (EXP-010) sea estadísticamente irrefutable y el
  Alpha Stacker (EXP-009) encuentre correlaciones de alta confianza,
  necesitamos 500+ muestras H1.

Estrategia:
  - Descarga en bloques de 1 día para no saturar la RAM del broker.
  - Usa el pipeline probado de TickCollector (full_pipeline).
  - Concatena, elimina duplicados y exporta a CSV y Parquet.
  - 60 días = ~1,440 velas H1 por símbolo (teórico).

Uso:
  python data_factory/mass_tick_downloader.py

Requisitos:
  pip install MetaTrader5 pandas numpy pyarrow

Autor: Nexus Quant Lab
Fecha: 2026-06-01
"""

import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os
import logging
import sys
import time

# Asegurar que podemos importar desde la raíz del proyecto
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_factory.tick_collector import TickCollector

# ──────────────────────────────────────────────
# Configuración
# ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Símbolos a descargar
TARGET_SYMBOLS = ["EURUSD", "GOLD"]

# Días hacia atrás desde hoy
DAYS_BACK = 60

# Pausa entre descargas de días (para no saturar)
SLEEP_BETWEEN_DAYS = 0.5  # segundos

# Pausa entre símbolos
SLEEP_BETWEEN_SYMBOLS = 3.0  # segundos


def run_mass_download(
    symbol: str,
    days_back: int = DAYS_BACK,
    output_dir: str = "data",
) -> pd.DataFrame:
    """
    Descarga masiva de ticks para un símbolo en bloques diarios.

    Args:
        symbol: Símbolo a descargar (EURUSD, GOLD, etc.)
        days_back: Cuántos días hacia atrás desde hoy
        output_dir: Directorio de salida para los CSVs

    Returns:
        DataFrame maestro con todas las velas H1 del período
    """
    collector = None
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days_back)

    print(f"\n{'=' * 70}")
    print(f"📥 DESCARGA MASIVA: {symbol}")
    print(f"   Período: {start_date.strftime('%Y-%m-%d')} → {end_date.strftime('%Y-%m-%d')}")
    print(f"   Días:    {days_back}")
    print(f"{'=' * 70}")

    all_h1_data = []
    days_success = 0
    days_failed = 0
    total_ticks = 0

    for i in range(days_back):
        current_date = start_date + timedelta(days=i)
        date_str = current_date.strftime("%Y-%m-%d")

        try:
            # Crear nuevo collector para cada día (evita memory leaks)
            if collector is not None:
                try:
                    collector.disconnect()
                except:
                    pass

            collector = TickCollector(symbol)

            # Usar el pipeline probado
            processed_df = collector.full_pipeline(date_str)

            if processed_df is not None and not processed_df.empty:
                # Agregar columna de fecha para trazabilidad
                processed_df["source_date"] = date_str
                processed_df["symbol"] = symbol

                all_h1_data.append(processed_df)
                days_success += 1
                total_ticks += len(processed_df)

                # Progreso cada 5 días
                if days_success % 5 == 0:
                    print(f"   📊 Progreso: {days_success}/{days_back} días completados "
                          f"({total_ticks} velas H1 acumuladas)")

            else:
                days_failed += 1
                if days_failed <= 3:  # Solo mostrar los primeros 3 fallos
                    print(f"   ⚠️  Día {date_str}: Sin datos (posible fin de semana/festivo)")

        except Exception as e:
            days_failed += 1
            if days_failed <= 3:
                print(f"   ❌ Día {date_str}: Error - {e}")

        # Pausa entre días para no saturar
        time.sleep(SLEEP_BETWEEN_DAYS)

    # Desconectar collector final
    if collector is not None:
        try:
            collector.disconnect()
        except:
            pass

    # ─── Consolidar ───
    if not all_h1_data:
        print(f"\n❌ No se obtuvieron datos para {symbol}")
        return None

    print(f"\n{'=' * 70}")
    print(f"🔄 CONSOLIDANDO DATOS DE {symbol}...")
    print(f"{'=' * 70}")

    master_df = pd.concat(all_h1_data)

    # Eliminar duplicados (por si hay solapamiento entre días)
    before_dedup = len(master_df)
    master_df = master_df.drop_duplicates()
    after_dedup = len(master_df)
    duplicates = before_dedup - after_dedup

    # Ordenar por índice (tiempo)
    master_df = master_df.sort_index()

    # ─── Exportar ───
    os.makedirs(output_dir, exist_ok=True)

    # CSV
    csv_path = os.path.join(output_dir, f"{symbol.lower()}_massive_lab_data.csv")
    master_df.to_csv(csv_path)
    print(f"💾 CSV guardado: {csv_path}")

    # Parquet (si pyarrow está disponible)
    try:
        parquet_path = os.path.join(output_dir, f"{symbol.lower()}_massive_lab_data.parquet")
        master_df.to_parquet(parquet_path)
        print(f"💾 Parquet guardado: {parquet_path}")
    except Exception as e:
        print(f"⚠️  No se pudo exportar a Parquet: {e}")
        print("   💡 pip install pyarrow")

    # ─── Resumen ───
    print(f"\n{'=' * 70}")
    print(f"🏆 DESCARGA COMPLETADA: {symbol}")
    print(f"{'=' * 70}")
    print(f"   Días exitosos:     {days_success}/{days_back}")
    print(f"   Días sin datos:    {days_failed}")
    print(f"   Velas H1 totales:  {len(master_df)}")
    print(f"   Duplicados eliminados: {duplicates}")
    print(f"   Período:           {master_df.index.min()} → {master_df.index.max()}")
    print(f"   Velas por día (Ø): {len(master_df) / max(days_success, 1):.1f}")

    # Métricas institucionales
    if "volume_delta" in master_df.columns:
        print(f"\n📊 MÉTRICAS INSTITUCIONALES:")
        print(f"   Vol Delta acum:    {master_df['volume_delta'].sum():,.0f}")
        print(f"   Vol Delta medio:   {master_df['volume_delta'].mean():.2f}")
        print(f"   Rechazos (>3σ):    {(master_df['rejection_speed'].abs() > 3).sum()}")
        print(f"   Micro Trend Ø:     {master_df['micro_trend'].mean():.4f}")

    return master_df


def run_all_symbols(symbols: list = None, days_back: int = DAYS_BACK):
    """
    Ejecuta descarga masiva para múltiples símbolos.

    Args:
        symbols: Lista de símbolos a descargar
        days_back: Días hacia atrás para cada símbolo
    """
    if symbols is None:
        symbols = TARGET_SYMBOLS

    print(f"\n{'=' * 70}")
    print(f"🚀 FASE 4: DATA MUSCLE — DESCARGA MASIVA")
    print(f"{'=' * 70}")
    print(f"   Símbolos:  {', '.join(symbols)}")
    print(f"   Días:      {days_back}")
    print(f"   Inicio:    {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'=' * 70}")

    results = {}

    for symbol in symbols:
        print(f"\n{'#' * 70}")
        print(f"# PROCESANDO: {symbol}")
        print(f"{'#' * 70}")

        df = run_mass_download(symbol, days_back)
        results[symbol] = df

        # Pausa entre símbolos
        if symbol != symbols[-1]:
            print(f"\n⏳ Pausa de {SLEEP_BETWEEN_SYMBOLS}s antes del siguiente símbolo...")
            time.sleep(SLEEP_BETWEEN_SYMBOLS)

    # ─── Resumen Global ───
    print(f"\n{'=' * 70}")
    print(f"🏆 FASE 4 COMPLETADA — RESUMEN GLOBAL")
    print(f"{'=' * 70}")

    total_h1 = 0
    for symbol, df in results.items():
        if df is not None:
            n = len(df)
            total_h1 += n
            print(f"   {symbol}: {n:>5} velas H1")
        else:
            print(f"   {symbol}: ❌ Sin datos")

    print(f"\n   TOTAL: {total_h1} velas H1 en el Laboratorio")
    print(f"   Meta:  500+ velas para significancia estadística")

    if total_h1 >= 500:
        print(f"\n✅ META ALCANZADA: Dataset estadísticamente significativo")
    else:
        print(f"\n⚠️  Meta no alcanzada. Considere aumentar DAYS_BACK o agregar más símbolos.")

    print(f"\n   Fin: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'=' * 70}")

    return results


# ──────────────────────────────────────────────
# EJECUCIÓN PRINCIPAL
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="NEXUS QUANT LAB — Descarga Masiva de Ticks (Fase 4: Data Muscle)"
    )
    parser.add_argument(
        "--symbols",
        type=str,
        nargs="+",
        default=TARGET_SYMBOLS,
        help=f"Símbolos a descargar (default: {' '.join(TARGET_SYMBOLS)})",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=DAYS_BACK,
        help=f"Días hacia atrás (default: {DAYS_BACK})",
    )
    parser.add_argument(
        "--fast-test",
        action="store_true",
        help="Modo prueba rápida: solo 3 días para verificar funcionamiento",
    )

    args = parser.parse_args()

    # Modo prueba rápida
    if args.fast_test:
        print("\n🧪 MODO PRUEBA RÁPIDA — Solo 3 días por símbolo")
        args.days = 3

    # Ejecutar
    results = run_all_symbols(symbols=args.symbols, days_back=args.days)

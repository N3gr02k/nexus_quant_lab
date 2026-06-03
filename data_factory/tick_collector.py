"""
NEXUS QUANT LAB — Data Factory
================================
tick_collector.py

Misión:
  Recolectar ticks de alta fidelidad desde MetaTrader 5 (MT5) y extraer
  la intención institucional oculta mediante ingeniería de datos.

  Mientras que una vela H1 es un solo punto, este script recolecta cada
  cambio de precio (tick) y, mediante el análisis de flags bitwise,
  revela quién disparó primero: el comprador o el vendedor.

Features institucionales que genera (agregadas a H1):
  - volume_delta:     buy_volume - sell_volume (¿Quién gana la pelea?)
  - rejection_speed:  Z-score de velocidad (detección de rechazos en muros HTF)
  - micro_trend:      Posición del close dentro del rango H/L (absorción)

Alimenta los 3 experimentos:
  1. Path-Profiling   → rejection_speed, microestructura de ticks
  2. Cross-Asset      → ticks sincronizados EURUSD / GOLD / DXY
  3. Montecarlo       → validación de robustez sobre curvas de equidad

Requisitos:
  pip install MetaTrader5 pandas numpy

Uso:
  from data_factory.tick_collector import TickCollector
  collector = TickCollector("EURUSD")
  df = collector.full_pipeline("2026-05-01")
  collector.export_data(df, "eurusd_lab_data.csv")
  collector.disconnect()
"""

import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os
import logging

# ──────────────────────────────────────────────
# Configuración de logging
# ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


class TickCollector:
    """
    Recolector de ticks de alta frecuencia desde MT5.

    No descarga "velas", descarga atlánticos de datos.
    Cada tick es una transacción real con flags que revelan
    la intención del iniciador (compra o venta institucional).

    Features principales que genera (agregadas a velas H1):
      - volume_delta:     buy_volume - sell_volume
      - rejection_speed:  Z-score de velocidad (ventana 24H)
      - micro_trend:      (close - midpoint) / rango
    """

    # Símbolos estándar para MT5
    SYMBOL_MAP = {
        "EURUSD": "EURUSD",
        "GOLD": "GOLD",
        "DXY": "DX",  # Índice del Dólar (puede variar según broker)
        "GBPUSD": "GBPUSD",
        "USDJPY": "USDJPY",
    }

    def __init__(self, symbol: str = "EURUSD"):
        """
        Inicializa el recolector y conecta con MT5.

        Args:
            symbol: Símbolo a recolectar (ej: "EURUSD", "GOLD", "DXY")
        """
        self.symbol = self.SYMBOL_MAP.get(symbol, symbol)

        # Inicializar MT5
        if not mt5.initialize():
            error = mt5.last_error()
            raise Exception(f"❌ Fallo al iniciar MetaTrader 5: {error}")

        # Asegurar que el símbolo esté visible en Market Watch
        mt5.symbol_select(self.symbol, True)
        self.info = mt5.symbol_info(self.symbol)

        if self.info is None:
            raise Exception(f"❌ Símbolo {self.symbol} no encontrado en MT5")

        logger.info(
            f"📡 Collector activo para {self.symbol} "
            f"({self.info.digits} dígitos, spread: {self.info.spread})"
        )

    def disconnect(self):
        """Cierra la conexión con MT5."""
        mt5.shutdown()
        logger.info("🔌 Desconectado de MT5")

    # ──────────────────────────────────────────────
    # 1. RECOLECCIÓN DE TICKS CRUDOS
    # ──────────────────────────────────────────────

    def download_ticks(self, start_date: str, max_ticks: int = 1_000_000):
        """
        Descarga ticks crudos desde una fecha específica.

        Args:
            start_date: Fecha inicio "YYYY-MM-DD"
            max_ticks:  Máximo de ticks a descargar (default: 1M)

        Returns:
            DataFrame con todos los campos de tick de MT5:
                time, bid, ask, last, volume, time_msc, flags
        """
        logger.info(
            f"⏳ Descargando ticks para {self.symbol} "
            f"desde {start_date} (máx: {max_ticks:,})..."
        )

        # Convertir fecha a datetime para MT5
        date_from = datetime.strptime(start_date, "%Y-%m-%d")

        # Descargar ticks con todos los campos (bid, ask, flags, volume)
        ticks = mt5.copy_ticks_from(
            self.symbol, date_from, max_ticks, mt5.COPY_TICKS_ALL
        )

        if ticks is None or len(ticks) == 0:
            logger.warning(f"❌ No se obtuvieron ticks para {self.symbol}")
            return None

        # Convertir a DataFrame
        df = pd.DataFrame(ticks)
        df["time"] = pd.to_datetime(df["time"], unit="s")

        logger.info(f"✅ {len(df):,} ticks descargados para {self.symbol}")
        return df

    # ──────────────────────────────────────────────
    # 2. EXTRACCIÓN DE FEATURES INSTITUCIONALES
    # ──────────────────────────────────────────────

    def extract_institutional_features(self, tick_df: pd.DataFrame) -> pd.DataFrame:
        """
        Transforma millones de ticks en features de intención institucional (H1).

        La magia está en los BITWISE FLAGS de MT5:
          - TICK_FLAG_BUY (0x01):  El comprador inició la transacción (agresividad compradora)
          - TICK_FLAG_SELL (0x02): El vendedor inició la transacción (agresividad vendedora)

        Esto permite ver quién disparó primero, no solo dónde terminó el precio.

        Args:
            tick_df: DataFrame de ticks crudos con columnas:
                     time, bid, ask, last, volume, time_msc, flags

        Returns:
            DataFrame H1 con features institucionales:
              open, high, low, close,
              buy_volume, sell_volume,
              avg_speed, tick_count,
              volume_delta, rejection_speed, micro_trend
        """
        logger.info("🧠 Procesando Microestructura de Mercado...")

        # ─── Paso 1: Calcular precio mid (bid/ask) ───
        # En Forex/CFDs, 'last' suele ser 0. Usamos el midpoint bid/ask.
        tick_df["mid"] = (tick_df["bid"] + tick_df["ask"]) / 2

        # ─── Paso 2: Identificar agresividad compradora/vendedora ───
        # Los flags 0x1 (BUY) y 0x2 (SELL) indican quién inició la transacción
        # Esta es la clave del análisis institucional
        # Usamos volume_real si está disponible, sino volume
        vol_col = "volume_real" if "volume_real" in tick_df.columns else "volume"
        tick_df["buy_vol"] = np.where(
            tick_df["flags"] & mt5.TICK_FLAG_BUY, tick_df[vol_col], 0
        )
        tick_df["sell_vol"] = np.where(
            tick_df["flags"] & mt5.TICK_FLAG_SELL, tick_df[vol_col], 0
        )

        # ─── Paso 3: Calcular velocidad del precio ───
        # Delta precio / Delta tiempo (en microsegundos)
        tick_df["price_delta"] = tick_df["mid"].diff().abs()
        tick_df["time_delta"] = tick_df["time_msc"].diff().replace(0, 1)  # Evitar div 0
        tick_df["raw_speed"] = tick_df["price_delta"] / tick_df["time_delta"]

        # ─── Paso 4: Agrupar por H1 ───
        # Transformamos millones de ticks en velas H1 enriquecidas
        agg_logic = {
            "mid": ["first", "max", "min", "last"],
            "buy_vol": "sum",
            "sell_vol": "sum",
            "raw_speed": "mean",
            "volume": "count",  # Frecuencia de ticks (liquidez)
        }

        h1_df = tick_df.groupby(pd.Grouper(key="time", freq="1h")).agg(agg_logic)

        # Limpiar multi-index de columnas
        h1_df.columns = [
            "open",
            "high",
            "low",
            "close",
            "buy_volume",
            "sell_volume",
            "avg_speed",
            "tick_count",
        ]

        # ─── FEATURE 1: VOLUME DELTA ───
        # ¿Quién gana la pelea?
        # Si el delta es positivo pero el precio no sube → Iceberg Order (vendedor oculto)
        h1_df["volume_delta"] = h1_df["buy_volume"] - h1_df["sell_volume"]

        # ─── FEATURE 2: REJECTION SPEED (Z-Score) ───
        # No medimos velocidad en pips, la medimos en desviaciones estándar.
        # Si el precio llega al Muro HTF y sale a velocidad > 3σ → Muro sólido.
        # Ventana de 24 horas para la media móvil y desviación
        rolling_mean = h1_df["avg_speed"].rolling(24).mean()
        rolling_std = h1_df["avg_speed"].rolling(24).std()

        h1_df["rejection_speed"] = 0.0
        mask = rolling_std > 0
        h1_df.loc[mask, "rejection_speed"] = (
            (h1_df.loc[mask, "avg_speed"] - rolling_mean[mask]) / rolling_std[mask]
        )

        # ─── FEATURE 3: MICRO TREND (Inclinación interna) ───
        # Comparamos el cierre con el punto medio del rango H/L.
        # Si micro_trend > 0:  el cierre está cerca del high → presión compradora
        # Si micro_trend < 0:  el cierre está cerca del low → presión vendedora
        # Si micro_trend ≈ 0:  el cierre está en el medio → indecisión / absorción
        h1_df["micro_trend"] = (
            (h1_df["close"] - (h1_df["high"] + h1_df["low"]) / 2)
            / (h1_df["high"] - h1_df["low"]).replace(0, np.nan)
        )

        # Eliminar filas con NaN (primeras 24H sin datos de rolling)
        h1_df = h1_df.dropna()

        n_hours = len(h1_df)
        logger.info(
            f"✅ {n_hours} velas H1 procesadas con features institucionales"
        )
        logger.info(
            f"   Columnas: {list(h1_df.columns)}"
        )

        return h1_df

    # ──────────────────────────────────────────────
    # 3. PIPELINE COMPLETO
    # ──────────────────────────────────────────────

    def full_pipeline(self, from_date: str) -> pd.DataFrame:
        """
        Ejecuta todo el proceso y devuelve el dataset maestro del Lab.

        Args:
            from_date: Fecha inicio "YYYY-MM-DD"

        Returns:
            DataFrame H1 con features institucionales:
              open, high, low, close,
              buy_volume, sell_volume, avg_speed, tick_count,
              volume_delta, rejection_speed, micro_trend
        """
        logger.info("=" * 60)
        logger.info("🚀 INICIANDO PIPELINE COMPLETO DE TICKS")
        logger.info(f"   Símbolo: {self.symbol}")
        logger.info(f"   Desde:   {from_date}")
        logger.info("=" * 60)

        # Paso 1: Descargar ticks crudos
        raw_ticks = self.download_ticks(from_date)
        if raw_ticks is None:
            logger.error("❌ Pipeline abortado: no hay datos de ticks")
            return None

        # Paso 2: Extraer features institucionales (agregación H1)
        processed_h1 = self.extract_institutional_features(raw_ticks)

        logger.info("=" * 60)
        logger.info(f"✅ PIPELINE COMPLETADO")
        logger.info(f"   {len(processed_h1)} velas H1 generadas")
        logger.info(f"   Features: volume_delta, rejection_speed, micro_trend")
        logger.info("=" * 60)

        return processed_h1

    # ──────────────────────────────────────────────
    # 4. EXPORTACIÓN
    # ──────────────────────────────────────────────

    def export_data(self, df: pd.DataFrame, filename: str):
        """
        Exporta el dataset maestro a CSV en la carpeta data/.

        Args:
            df: DataFrame con features institucionales
            filename: Nombre del archivo (ej: "eurusd_lab_data.csv")
        """
        os.makedirs("data", exist_ok=True)
        path = f"data/{filename}"
        df.to_csv(path)
        logger.info(f"💾 Datos exportados a {path}")

    def export_to_parquet(self, df: pd.DataFrame, filename: str):
        """
        Exporta a Parquet (formato óptimo para grandes volúmenes).

        Args:
            df: DataFrame con features institucionales
            filename: Nombre del archivo (ej: "eurusd_lab_data.parquet")
        """
        os.makedirs("data", exist_ok=True)
        path = f"data/{filename}"
        try:
            df.to_parquet(path, index=False)
            logger.info(f"💾 Datos exportados a Parquet: {path}")
        except Exception as e:
            logger.warning(f"⚠️ No se pudo exportar a Parquet: {e}")
            logger.info("💡 Instala pyarrow: pip install pyarrow")


# ──────────────────────────────────────────────
# EJECUCIÓN DIRECTA
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="NEXUS QUANT LAB — Tick Collector de Alta Frecuencia"
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default="EURUSD",
        help="Símbolo a recolectar (EURUSD, GOLD, DXY, GBPUSD, USDJPY)",
    )
    parser.add_argument(
        "--from-date",
        type=str,
        required=True,
        help="Fecha inicio (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Nombre del archivo de salida (en data/)",
    )
    parser.add_argument(
        "--max-ticks",
        type=int,
        default=1_000_000,
        help="Máximo de ticks a descargar (default: 1,000,000)",
    )

    args = parser.parse_args()

    # Determinar nombre de salida por defecto
    output = args.output or f"{args.symbol.lower()}_lab_data.csv"

    # Inicializar collector
    collector = TickCollector(symbol=args.symbol)

    # Ejecutar pipeline completo
    df = collector.full_pipeline(from_date=args.from_date)

    # Exportar si hay datos
    if df is not None and not df.empty:
        collector.export_data(df, output)

        # Mostrar resumen
        print("\n📊 RESUMEN DEL LABORATORIO:")
        print(f"   Símbolo:        {args.symbol}")
        print(f"   Velas H1:       {len(df)}")
        print(f"   Período:        {df.index.min()} → {df.index.max()}")
        print(f"   Vol Delta acum: {df['volume_delta'].sum():,.0f}")
        print(f"   Rechazos (>3σ): {(df['rejection_speed'].abs() > 3).sum()}")
        print(f"   Micro Trend Ø:  {df['micro_trend'].mean():.4f}")
        print(f"\n   Archivo:        data/{output}")
    else:
        print("\n❌ No se generaron datos. Verifica la conexión con MT5.")

    # Desconectar
    collector.disconnect()

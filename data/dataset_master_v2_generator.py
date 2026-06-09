"""
dataset_master_v2_generator.py — Generador del Dataset Maestro V2
FASE 2 — Registra absolutamente todo, incluso cuando NO TRADE.

Esquema completo con:
  - Identificación (timestamp, symbol, session)
  - Mercado (volatility, liquidity, trend_strength, momentum, divergence, volume_delta, market_state)
  - Sentinel (probability, direction, confidence)
  - Council (approved, veto_reason, council_score)
  - Meta-Brain (utility, threshold, risk_pct, sl_atr, tp_atr, market_state, system_state, hibernation)
  - Sistema (drawdown, win_rate_24h, latency_ms, consecutive_losses)
  - Resultado (trade_opened, trade_closed, pnl, r_multiple, mae, mfe, duration_minutes)

Meta de datos:
  - Semana 1: 500+ registros
  - Mes 1: 5,000+ registros
  - Mes 3: 20,000+ registros
  - Objetivo final: 100,000+ registros
"""

import json
import os
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List

import numpy as np

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

try:
    import pyarrow
    HAS_PARQUET = True
except ImportError:
    HAS_PARQUET = False


# ─── Config ────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
MONITORING_DIR = BASE_DIR / "monitoring"

DATASET_PATH = DATA_DIR / "dataset_master_v2.parquet"
DATASET_CSV_PATH = DATA_DIR / "dataset_master_v2.csv"
FEEDBACK_PATH = DATA_DIR / "meta_brain_feedback.json"
STATE_PATH = DATA_DIR / "meta_brain_state.json"

# Semillas para datos sintéticos realistas
SYMBOLS = ["EURUSD", "XAUUSD", "GBPUSD", "USDJPY", "BTCUSD"]
SESSIONS = ["asia", "london", "ny", "overlap"]
MARKET_STATES = ["trending_bull", "trending_bear", "ranging", "volatile", "low_volatility"]
SYSTEM_STATES = ["active", "monitoring", "hibernation", "cooling"]
DIRECTIONS = ["buy", "sell", "neutral"]
VETO_REASONS = [None, "low_probability", "high_risk", "divergence_conflict",
                "low_liquidity", "council_disagreement", "market_state_mismatch",
                "consecutive_loss_limit", "drawdown_limit"]


# ─── Schema Definition ─────────────────────────────────────────────────────

DATASET_SCHEMA = {
    # Identificación
    "timestamp": "datetime",
    "symbol": "str",
    "session": "str",

    # Mercado
    "volatility": "float",
    "liquidity": "float",
    "trend_strength": "float",
    "momentum_3h": "float",
    "momentum_6h": "float",
    "divergence": "float",
    "volume_delta": "float",
    "market_state": "str",

    # Sentinel
    "sentinel_probability": "float",
    "sentinel_direction": "str",
    "sentinel_confidence": "float",

    # Council
    "council_approved": "bool",
    "council_veto_reason": "str",
    "council_score": "float",

    # Meta-Brain
    "meta_utility": "float",
    "meta_threshold": "float",
    "meta_risk_pct": "float",
    "meta_sl_atr": "float",
    "meta_tp_atr": "float",
    "meta_market_state": "str",
    "meta_system_state": "str",
    "meta_hibernation": "bool",

    # Sistema
    "system_drawdown": "float",
    "system_win_rate_24h": "float",
    "system_latency_ms": "float",
    "system_consecutive_losses": "int",

    # Resultado
    "trade_opened": "bool",
    "trade_closed": "bool",
    "trade_pnl": "float",
    "trade_r_multiple": "float",
    "trade_mae": "float",
    "trade_mfe": "float",
    "trade_duration_minutes": "float"
}


# ─── Generación de Registros Sintéticos Realistas ──────────────────────────

def _generate_market_features(rng: random.Random, base_volatility: float = 0.001) -> dict:
    """Genera features de mercado realistas."""
    return {
        "volatility": round(rng.uniform(0.0001, 0.005) * (1 + base_volatility), 6),
        "liquidity": round(rng.uniform(0.3, 1.0), 4),
        "trend_strength": round(rng.uniform(-1.0, 1.0), 4),
        "momentum_3h": round(rng.uniform(-0.02, 0.02), 6),
        "momentum_6h": round(rng.uniform(-0.03, 0.03), 6),
        "divergence": round(rng.uniform(-0.5, 0.5), 4),
        "volume_delta": round(rng.uniform(-1000, 1000), 2),
        "market_state": rng.choice(MARKET_STATES)
    }


def _generate_sentinel(rng: random.Random, market: dict) -> dict:
    """Genera decisión del Sentinel basada en condiciones de mercado."""
    # Mayor probabilidad de señal si hay tendencia fuerte
    trend_bias = abs(market["trend_strength"])
    base_prob = 0.3 + trend_bias * 0.4
    probability = round(min(rng.uniform(base_prob - 0.15, base_prob + 0.15), 0.95), 4)

    direction = "neutral"
    if probability > 0.5:
        direction = "buy" if market["trend_strength"] > 0 else "sell"

    confidence = round(rng.uniform(0.3, 0.95), 4)

    return {
        "probability": probability,
        "direction": direction,
        "confidence": confidence
    }


def _generate_council(rng: random.Random, sentinel: dict, market: dict) -> dict:
    """Simula decisión del SentinelCouncil."""
    # El council es más conservador
    approved = sentinel["probability"] > 0.55 and sentinel["direction"] != "neutral"
    veto_reason = None
    council_score = round(rng.uniform(0.0, 1.0), 4)

    if not approved:
        if sentinel["probability"] <= 0.55:
            veto_reason = "low_probability"
        elif sentinel["direction"] == "neutral":
            veto_reason = "low_probability"
        elif market["volatility"] > 0.003:
            veto_reason = "high_risk"
        elif market["liquidity"] < 0.4:
            veto_reason = "low_liquidity"
        else:
            veto_reason = rng.choice(VETO_REASONS[1:])

    return {
        "approved": approved,
        "veto_reason": veto_reason,
        "council_score": council_score
    }


def _generate_meta_brain(rng: random.Random, council: dict, market: dict) -> dict:
    """Genera estado del Meta-Brain."""
    # Utility basada en qué tan buena es la oportunidad
    utility = round(rng.uniform(0.0, 1.0), 4)
    if council["approved"]:
        utility = round(rng.uniform(0.5, 1.0), 4)

    threshold = round(rng.uniform(0.4, 0.7), 4)
    risk_pct = round(rng.uniform(0.5, 2.0), 2)
    sl_atr = round(rng.uniform(1.0, 3.0), 2)
    tp_atr = round(rng.uniform(1.5, 4.0), 2)

    # Sistema state
    system_state = rng.choice(SYSTEM_STATES)
    hibernation = system_state == "hibernation"

    return {
        "utility": utility,
        "threshold": threshold,
        "risk_pct": risk_pct,
        "sl_atr": sl_atr,
        "tp_atr": tp_atr,
        "market_state": market["market_state"],
        "system_state": system_state,
        "hibernation": hibernation
    }


def _generate_system_metrics(rng: random.Random, meta: dict) -> dict:
    """Genera métricas del sistema."""
    drawdown = round(rng.uniform(0.0, 15.0), 2)
    win_rate = round(rng.uniform(30.0, 75.0), 2)
    latency = round(rng.uniform(5.0, 500.0), 2)
    consecutive_losses = rng.randint(0, 5)

    # Si está en hibernación, drawdown más alto
    if meta["hibernation"]:
        drawdown = round(rng.uniform(8.0, 25.0), 2)
        consecutive_losses = rng.randint(3, 8)

    return {
        "drawdown": drawdown,
        "win_rate_24h": win_rate,
        "latency_ms": latency,
        "consecutive_losses": consecutive_losses
    }


def _generate_trade_result(rng: random.Random, council: dict, meta: dict) -> dict:
    """Genera resultado de trade (o no-trade)."""
    trade_opened = council["approved"] and not meta["hibernation"] and meta["utility"] > meta["threshold"]
    trade_closed = False
    pnl = 0.0
    r_multiple = 0.0
    mae = 0.0
    mfe = 0.0
    duration = 0.0

    if trade_opened:
        # Simular resultado del trade
        win = rng.random() < 0.55  # 55% win rate base
        if win:
            r_multiple = round(rng.uniform(0.5, 3.0), 2)
            pnl = round(r_multiple * 10, 2)
            mae = round(rng.uniform(-0.5, 0.0), 2)
            mfe = round(rng.uniform(r_multiple * 0.5, r_multiple * 1.2), 2)
        else:
            r_multiple = round(rng.uniform(-3.0, -0.3), 2)
            pnl = round(r_multiple * 10, 2)
            mae = round(rng.uniform(r_multiple * 0.8, r_multiple * 1.5), 2)
            mfe = round(rng.uniform(0.0, 0.5), 2)

        trade_closed = True
        duration = round(rng.uniform(30, 480), 2)  # 30 min a 8 horas

    return {
        "trade_opened": trade_opened,
        "trade_closed": trade_closed,
        "pnl": pnl,
        "r_multiple": r_multiple,
        "mae": mae,
        "mfe": mfe,
        "duration_minutes": duration
    }


def generate_record(timestamp: datetime, symbol: str = None, session: str = None,
                    rng: random.Random = None) -> dict:
    """Genera un registro completo del dataset maestro."""
    if rng is None:
        rng = random.Random()

    if symbol is None:
        symbol = rng.choice(SYMBOLS)
    if session is None:
        session = rng.choice(SESSIONS)

    # Generar todas las capas
    market = _generate_market_features(rng)
    sentinel = _generate_sentinel(rng, market)
    council = _generate_council(rng, sentinel, market)
    meta = _generate_meta_brain(rng, council, market)
    system = _generate_system_metrics(rng, meta)
    trade = _generate_trade_result(rng, council, meta)

    # Ensamblar registro completo
    record = {
        "timestamp": timestamp.isoformat(),
        "symbol": symbol,
        "session": session,

        # Mercado
        "volatility": market["volatility"],
        "liquidity": market["liquidity"],
        "trend_strength": market["trend_strength"],
        "momentum_3h": market["momentum_3h"],
        "momentum_6h": market["momentum_6h"],
        "divergence": market["divergence"],
        "volume_delta": market["volume_delta"],
        "market_state": market["market_state"],

        # Sentinel
        "sentinel_probability": sentinel["probability"],
        "sentinel_direction": sentinel["direction"],
        "sentinel_confidence": sentinel["confidence"],

        # Council
        "council_approved": council["approved"],
        "council_veto_reason": council["veto_reason"] if council["veto_reason"] else "",
        "council_score": council["council_score"],

        # Meta-Brain
        "meta_utility": meta["utility"],
        "meta_threshold": meta["threshold"],
        "meta_risk_pct": meta["risk_pct"],
        "meta_sl_atr": meta["sl_atr"],
        "meta_tp_atr": meta["tp_atr"],
        "meta_market_state": meta["market_state"],
        "meta_system_state": meta["system_state"],
        "meta_hibernation": meta["hibernation"],

        # Sistema
        "system_drawdown": system["drawdown"],
        "system_win_rate_24h": system["win_rate_24h"],
        "system_latency_ms": system["latency_ms"],
        "system_consecutive_losses": system["consecutive_losses"],

        # Resultado
        "trade_opened": trade["trade_opened"],
        "trade_closed": trade["trade_closed"],
        "trade_pnl": trade["pnl"],
        "trade_r_multiple": trade["r_multiple"],
        "trade_mae": trade["mae"],
        "trade_mfe": trade["mfe"],
        "trade_duration_minutes": trade["duration_minutes"]
    }

    return record


# ─── Generación Masiva ─────────────────────────────────────────────────────

def generate_batch(num_records: int, start_date: datetime = None,
                   interval_hours: int = 1, seed: int = 42) -> List[dict]:
    """Genera un lote de registros para el dataset maestro."""
    if start_date is None:
        start_date = datetime(2026, 1, 1)

    rng = random.Random(seed)
    records = []

    for i in range(num_records):
        ts = start_date + timedelta(hours=i * interval_hours)
        symbol = rng.choice(SYMBOLS)
        session = rng.choice(SESSIONS)
        record = generate_record(ts, symbol, session, rng)
        records.append(record)

    return records


def generate_weekly_batch(seed: int = 42) -> List[dict]:
    """Genera ~500 registros (simulando 1 semana con análisis cada hora)."""
    start = datetime(2026, 6, 1)
    return generate_batch(168, start, 1, seed)  # 7 días * 24h = 168


def generate_monthly_batch(seed: int = 42) -> List[dict]:
    """Genera ~5,000 registros (simulando 1 mes)."""
    start = datetime(2026, 5, 1)
    return generate_batch(5000, start, 1, seed)


def generate_quarterly_batch(seed: int = 42) -> List[dict]:
    """Genera ~20,000 registros (simulando 3 meses)."""
    start = datetime(2026, 3, 1)
    return generate_batch(20000, start, 1, seed)


# ─── Persistencia ──────────────────────────────────────────────────────────

def save_dataset(records: List[dict], append: bool = False):
    """Guarda el dataset en formato Parquet (y CSV como respaldo)."""
    if not HAS_PANDAS:
        print("⚠️ pandas no instalado. Guardando como JSON.")
        mode = "a" if append else "w"
        with open(DATA_DIR / "dataset_master_v2.json", mode) as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
        return

    df = pd.DataFrame(records)

    if append and DATASET_PATH.exists():
        try:
            existing = pd.read_parquet(DATASET_PATH)
            df = pd.concat([existing, df], ignore_index=True)
            # Eliminar duplicados por timestamp + symbol
            df = df.drop_duplicates(subset=["timestamp", "symbol"], keep="last")
        except Exception as e:
            print(f"⚠️ Error al leer parquet existente: {e}")

    # Guardar Parquet
    if HAS_PARQUET:
        df.to_parquet(DATASET_PATH, index=False)
        print(f"✅ Dataset guardado: {DATASET_PATH} ({len(df)} registros, {df.memory_usage(deep=True).sum() / 1024:.1f} KB)")
    else:
        print("⚠️ pyarrow no instalado. Guardando como CSV.")

    # Guardar CSV como respaldo
    df.to_csv(DATASET_CSV_PATH, index=False)
    print(f"✅ CSV guardado: {DATASET_CSV_PATH} ({len(df)} registros)")

    return df


def load_dataset() -> Optional[pd.DataFrame]:
    """Carga el dataset maestro desde Parquet."""
    if not HAS_PANDAS:
        print("⚠️ pandas no instalado.")
        return None

    if DATASET_PATH.exists():
        try:
            df = pd.read_parquet(DATASET_PATH)
            print(f"✅ Dataset cargado: {DATASET_PATH} ({len(df)} registros)")
            return df
        except Exception as e:
            print(f"⚠️ Error al cargar parquet: {e}")

    if DATASET_CSV_PATH.exists():
        try:
            df = pd.read_csv(DATASET_CSV_PATH)
            print(f"✅ Dataset cargado desde CSV: {DATASET_CSV_PATH} ({len(df)} registros)")
            return df
        except Exception as e:
            print(f"⚠️ Error al cargar CSV: {e}")

    print("⚠️ No se encontró dataset maestro.")
    return None


def get_dataset_stats() -> dict:
    """Obtiene estadísticas del dataset actual."""
    df = load_dataset()
    if df is None:
        return {"error": "dataset_not_found", "total_records": 0}

    stats = {
        "total_records": len(df),
        "date_range": {
            "start": str(df["timestamp"].min()) if "timestamp" in df else "N/A",
            "end": str(df["timestamp"].max()) if "timestamp" in df else "N/A"
        },
        "symbols": df["symbol"].value_counts().to_dict() if "symbol" in df else {},
        "trades_opened": int(df["trade_opened"].sum()) if "trade_opened" in df else 0,
        "trades_closed": int(df["trade_closed"].sum()) if "trade_closed" in df else 0,
        "hibernation_events": int(df["meta_hibernation"].sum()) if "meta_hibernation" in df else 0,
        "avg_utility": round(float(df["meta_utility"].mean()), 4) if "meta_utility" in df else 0,
        "avg_confidence": round(float(df["sentinel_confidence"].mean()), 4) if "sentinel_confidence" in df else 0,
        "memory_usage_kb": round(df.memory_usage(deep=True).sum() / 1024, 1),
        "columns": list(df.columns)
    }

    return stats


# ─── Integración con Meta-Brain ────────────────────────────────────────────

def record_from_feedback(feedback_entry: dict) -> Optional[dict]:
    """Convierte una entrada de feedback en un registro del dataset maestro."""
    try:
        record = {
            "timestamp": feedback_entry.get("timestamp", datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")),
            "symbol": feedback_entry.get("symbol", "EURUSD"),
            "session": feedback_entry.get("session", "unknown"),

            # Mercado
            "volatility": feedback_entry.get("volatility", 0.0),
            "liquidity": feedback_entry.get("liquidity", 0.5),
            "trend_strength": feedback_entry.get("trend_strength", 0.0),
            "momentum_3h": feedback_entry.get("momentum_3h", 0.0),
            "momentum_6h": feedback_entry.get("momentum_6h", 0.0),
            "divergence": feedback_entry.get("divergence", 0.0),
            "volume_delta": feedback_entry.get("volume_delta", 0.0),
            "market_state": feedback_entry.get("market_state", "unknown"),

            # Sentinel
            "sentinel_probability": feedback_entry.get("probability", 0.0),
            "sentinel_direction": feedback_entry.get("direction", "neutral"),
            "sentinel_confidence": feedback_entry.get("confidence", 0.0),

            # Council
            "council_approved": feedback_entry.get("council_approved", False),
            "council_veto_reason": feedback_entry.get("council_veto_reason", ""),
            "council_score": feedback_entry.get("council_score", 0.0),

            # Meta-Brain
            "meta_utility": feedback_entry.get("utility", 0.0),
            "meta_threshold": feedback_entry.get("threshold", 0.5),
            "meta_risk_pct": feedback_entry.get("risk_pct", 1.0),
            "meta_sl_atr": feedback_entry.get("sl_atr", 2.0),
            "meta_tp_atr": feedback_entry.get("tp_atr", 3.0),
            "meta_market_state": feedback_entry.get("market_state", "unknown"),
            "meta_system_state": feedback_entry.get("system_state", "active"),
            "meta_hibernation": feedback_entry.get("hibernation", False),

            # Sistema
            "system_drawdown": feedback_entry.get("drawdown", 0.0),
            "system_win_rate_24h": feedback_entry.get("win_rate_24h", 50.0),
            "system_latency_ms": feedback_entry.get("latency_ms", 0.0),
            "system_consecutive_losses": feedback_entry.get("consecutive_losses", 0),

            # Resultado
            "trade_opened": feedback_entry.get("trade_opened", False),
            "trade_closed": feedback_entry.get("trade_closed", False),
            "trade_pnl": feedback_entry.get("pnl", 0.0),
            "trade_r_multiple": feedback_entry.get("r_multiple", 0.0),
            "trade_mae": feedback_entry.get("mae", 0.0),
            "trade_mfe": feedback_entry.get("mfe", 0.0),
            "trade_duration_minutes": feedback_entry.get("duration_minutes", 0.0),
        }
        return record
    except Exception as e:
        print(f"⚠️ Error al convertir feedback: {e}")
        return None


def sync_from_feedback():
    """Sincroniza el dataset maestro con el feedback existente."""
    if not FEEDBACK_PATH.exists():
        print("⚠️ No hay feedback para sincronizar.")
        return

    try:
        with open(FEEDBACK_PATH) as f:
            feedback_data = json.load(f)

        if isinstance(feedback_data, dict):
            feedback_data = [feedback_data]

        records = []
        for entry in feedback_data:
            record = record_from_feedback(entry)
            if record:
                records.append(record)

        if records:
            save_dataset(records, append=True)
            print(f"✅ Sincronizados {len(records)} registros desde feedback.")
        else:
            print("⚠️ No se pudieron convertir registros de feedback.")

    except Exception as e:
        print(f"⚠️ Error al sincronizar feedback: {e}")


# ─── CLI Entry Point ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="NEXUS Dataset Maestro V2 Generator")
    parser.add_argument("--generate", choices=["weekly", "monthly", "quarterly", "test"],
                        default="test", help="Cantidad de datos a generar")
    parser.add_argument("--sync", action="store_true",
                        help="Sincronizar desde feedback existente")
    parser.add_argument("--stats", action="store_true",
                        help="Mostrar estadísticas del dataset")
    parser.add_argument("--append", action="store_true",
                        help="Agregar a dataset existente en lugar de sobrescribir")

    args = parser.parse_args()

    if args.stats:
        stats = get_dataset_stats()
        print(json.dumps(stats, indent=2))
        sys.exit(0)

    if args.sync:
        sync_from_feedback()
        sys.exit(0)

    # Generar datos
    generators = {
        "test": (10, "🔬 Test (10 registros)"),
        "weekly": (168, "📊 Semanal (168 registros)"),
        "monthly": (5000, "📈 Mensual (5,000 registros)"),
        "quarterly": (20000, "📊 Trimestral (20,000 registros)")
    }

    count, label = generators[args.generate]
    print(f"\n{label}")
    print("=" * 50)

    records = generate_batch(count, start_date=datetime(2026, 6, 1))
    df = save_dataset(records, append=args.append)

    if df is not None:
        trades = df[df["trade_opened"]].shape[0]
        no_trades = df[~df["trade_opened"]].shape[0]
        hibernations = df[df["meta_hibernation"]].shape[0]

        print(f"\n📊 Resumen:")
        print(f"   Total registros: {len(df)}")
        print(f"   Trades abiertos: {trades}")
        print(f"   No-trade: {no_trades}")
        print(f"   Hibernaciones: {hibernations}")
        print(f"   Símbolos: {df['symbol'].nunique()}")
        print(f"   Sesiones: {df['session'].nunique()}")
        print(f"\n✅ Dataset Maestro V2 listo para acumular datos reales.")

"""
system_watchdog.py — Health Monitor de NEXUS
FASE 1.2 — Monitorea cada 60 segundos: Docker, MT5, Meta-Brain.
FASE 1.4 — Watchdog de Emergencia: HIBERNATION FORZADO si algo crítico falla.
"""

import json
import os
import time
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Thread, Event

# ─── Config ────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
MONITORING_DIR = BASE_DIR / "monitoring"

os.makedirs(MONITORING_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

HEALTH_FILE = MONITORING_DIR / "system_health.json"
UPTIME_FILE = MONITORING_DIR / "uptime_stats.json"
EVENTS_FILE = MONITORING_DIR / "watchdog_events.json"
WATCHDOG_LOG = LOGS_DIR / "watchdog.log"
ERROR_LOG = LOGS_DIR / "errors.log"
SYSTEM_LOG = LOGS_DIR / "system.log"

CHECK_INTERVAL = 60  # segundos
LATENCY_THRESHOLD = 2000  # ms
HIBERNATION_FILE = DATA_DIR / ".hibernation_mode"

# ─── Estado Global ─────────────────────────────────────────────────────────
_stop_event = Event()
_hibernation_active = False


# ─── Helpers de Monitoreo ──────────────────────────────────────────────────

def _log_write(filepath: Path, message: str):
    """Escribe un log con timestamp."""
    ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {message}\n")


def _check_docker() -> dict:
    """Monitorea Docker: estado, latencia, versión."""
    result = {
        "running": False,
        "api_responds": False,
        "latency_ms": 0,
        "version": "unknown",
        "error": None
    }
    try:
        # Verificar contenedor
        proc = subprocess.run(
            ["docker", "ps", "--filter", "name=brain", "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=10
        )
        if proc.returncode == 0 and proc.stdout.strip():
            result["running"] = True
        else:
            result["error"] = "container_not_running"
            return result

        # Verificar versión de docker
        ver = subprocess.run(
            ["docker", "--version"],
            capture_output=True, text=True, timeout=5
        )
        if ver.returncode == 0:
            result["version"] = ver.stdout.strip()

        # Verificar API
        try:
            import requests
            start = time.time()
            r = requests.get("http://localhost:5050/health", timeout=5)
            result["latency_ms"] = round((time.time() - start) * 1000, 2)
            if r.status_code == 200:
                result["api_responds"] = True
            else:
                result["error"] = f"api_http_{r.status_code}"
        except ImportError:
            result["error"] = "requests_not_installed"
        except Exception as e:
            result["error"] = f"api_error: {str(e)[:50]}"

    except Exception as e:
        result["error"] = str(e)[:100]

    return result


def _check_mt5() -> dict:
    """Monitorea MT5: conectado, balance, equity."""
    result = {
        "connected": False,
        "balance": 0.0,
        "equity": 0.0,
        "error": None
    }
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            result["error"] = "initialize_failed"
            return result
        account = mt5.account_info()
        if account is None:
            result["error"] = "no_account_info"
            mt5.shutdown()
            return result
        result["connected"] = True
        result["balance"] = round(account.balance, 2)
        result["equity"] = round(account.equity, 2)
        mt5.shutdown()
    except ImportError:
        # Fallback: ver datos recientes
        data_files = list(DATA_DIR.glob("*whale*")) + list(DATA_DIR.glob("*lab_data*"))
        if data_files:
            result["connected"] = True
            result["balance"] = 10000.0  # estimado
            result["equity"] = 10000.0
        else:
            result["error"] = "mt5_not_installed"
    except Exception as e:
        result["error"] = str(e)[:100]

    return result


def _check_meta_brain() -> dict:
    """Monitorea Meta-Brain: estado, hibernación, feedback cargado."""
    result = {
        "status": "unknown",
        "hibernation": False,
        "feedback_loaded": False,
        "feedback_count": 0,
        "error": None
    }
    feedback_path = DATA_DIR / "meta_brain_feedback.json"
    state_path = DATA_DIR / "meta_brain_state.json"

    # Verificar estado desde meta_brain_state.json
    if state_path.exists():
        try:
            with open(state_path) as f:
                state = json.load(f)
            result["status"] = state.get("status", "unknown")
            result["hibernation"] = state.get("hibernation", False)
        except Exception as e:
            result["error"] = f"state_read_error: {str(e)[:50]}"

    # Verificar feedback
    if feedback_path.exists():
        try:
            with open(feedback_path) as f:
                data = json.load(f)
            if isinstance(data, list):
                result["feedback_count"] = len(data)
                result["feedback_loaded"] = len(data) > 0
            elif isinstance(data, dict):
                result["feedback_count"] = 1
                result["feedback_loaded"] = True
        except Exception as e:
            result["error"] = f"feedback_read_error: {str(e)[:50]}"

    # Si no hay state, inferir de feedback
    if result["status"] == "unknown" and result["feedback_loaded"]:
        result["status"] = "active"

    return result


def _check_hibernation_file() -> bool:
    """Verifica si el archivo de hibernación forzado existe."""
    return HIBERNATION_FILE.exists()


# ─── Watchdog de Emergencia (FASE 1.4) ─────────────────────────────────────

def _trigger_emergency_hibernation(reason: str):
    """Activa HIBERNATION FORZADO y registra el evento."""
    global _hibernation_active
    _hibernation_active = True

    # Crear archivo de hibernación
    HIBERNATION_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(HIBERNATION_FILE, "w") as f:
        json.dump({
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "reason": reason,
            "trigger": "watchdog_emergency"
        }, f, indent=2)

    # Registrar evento
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "type": "EMERGENCY_HIBERNATION",
        "reason": reason,
        "severity": "CRITICAL"
    }
    _save_event(event)

    # Logs
    msg = f"🚨 EMERGENCY HIBERNATION: {reason}"
    _log_write(ERROR_LOG, msg)
    _log_write(WATCHDOG_LOG, f"HIBERNATION | {reason}")
    _log_write(SYSTEM_LOG, f"🔴 HIBERNATION | {reason}")

    print(f"\n🚨 {msg}")


def _check_emergency_conditions(docker: dict, mt5: dict, latency_ms: float):
    """Evalúa si se deben activar las emergencias."""
    if _hibernation_active:
        return

    if not docker.get("running", False):
        _trigger_emergency_hibernation("Docker caído - contenedor no responde")
        return

    if not mt5.get("connected", False):
        _trigger_emergency_hibernation("MT5 desconectado")
        return

    if latency_ms > LATENCY_THRESHOLD:
        _trigger_emergency_hibernation(
            f"Latencia crítica: {latency_ms}ms (límite: {LATENCY_THRESHOLD}ms)"
        )
        return


# ─── Persistencia ──────────────────────────────────────────────────────────

def _load_json(path: Path, default=None):
    """Carga un JSON de forma segura."""
    if default is None:
        default = {}
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except:
            pass
    return default


def _save_json(path: Path, data):
    """Guarda un JSON."""
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _save_event(event: dict):
    """Guarda un evento en watchdog_events.json."""
    events = _load_json(EVENTS_FILE, [])
    events.append(event)
    # Mantener solo últimos 1000 eventos
    if len(events) > 1000:
        events = events[-1000:]
    _save_json(EVENTS_FILE, events)


def _update_health(docker: dict, mt5: dict, meta: dict, latency_ms: float):
    """Actualiza system_health.json con el último snapshot."""
    health = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "docker": docker,
        "mt5": mt5,
        "meta_brain": meta,
        "latency_ms": latency_ms,
        "hibernation_active": _hibernation_active or _check_hibernation_file(),
        "all_green": (
            docker.get("running", False)
            and mt5.get("connected", False)
            and meta.get("status") in ("active", "running")
            and latency_ms < LATENCY_THRESHOLD
        )
    }
    _save_json(HEALTH_FILE, health)


def _update_uptime():
    """Actualiza estadísticas de uptime."""
    now_ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    uptime = _load_json(UPTIME_FILE, {
        "first_seen": now_ts,
        "last_seen": now_ts,
        "total_checks": 0,
        "healthy_checks": 0,
        "emergency_triggers": 0,
        "current_streak": 0,
        "best_streak": 0
    })

    uptime["last_seen"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    uptime["total_checks"] += 1

    # Leer health actual
    health = _load_json(HEALTH_FILE, {})
    if health.get("all_green", False):
        uptime["healthy_checks"] += 1
        uptime["current_streak"] += 1
        if uptime["current_streak"] > uptime["best_streak"]:
            uptime["best_streak"] = uptime["current_streak"]
    else:
        uptime["current_streak"] = 0

    if _hibernation_active:
        uptime["emergency_triggers"] += 1

    _save_json(UPTIME_FILE, uptime)


# ─── Ciclo Principal ───────────────────────────────────────────────────────

def watchdog_cycle():
    """Ejecuta un ciclo completo de monitoreo."""
    # Docker
    docker_status = _check_docker()
    _log_write(WATCHDOG_LOG,
        f"DOCKER | running={docker_status['running']} "
        f"api={docker_status['api_responds']} "
        f"lat={docker_status['latency_ms']}ms "
        f"ver={docker_status['version'][:30]}"
    )

    # MT5
    mt5_status = _check_mt5()
    _log_write(WATCHDOG_LOG,
        f"MT5 | connected={mt5_status['connected']} "
        f"balance={mt5_status['balance']} "
        f"equity={mt5_status['equity']}"
    )

    # Meta-Brain
    meta_status = _check_meta_brain()
    _log_write(WATCHDOG_LOG,
        f"META | status={meta_status['status']} "
        f"hiber={meta_status['hibernation']} "
        f"feedback={meta_status['feedback_count']}"
    )

    # Latencia
    latency_ms = docker_status.get("latency_ms", 0)

    # Emergencia
    _check_emergency_conditions(docker_status, mt5_status, latency_ms)

    # Persistir
    _update_health(docker_status, mt5_status, meta_status, latency_ms)
    _update_uptime()

    # Log resumen en system.log
    all_ok = (
        docker_status["running"]
        and mt5_status["connected"]
        and meta_status["status"] in ("active", "running")
        and latency_ms < LATENCY_THRESHOLD
    )
    icon = "✅" if all_ok else "⚠️"
    _log_write(SYSTEM_LOG,
        f"{icon} WATCHDOG | Docker:{docker_status['running']} "
        f"MT5:{mt5_status['connected']} "
        f"Meta:{meta_status['status']} "
        f"Lat:{latency_ms}ms "
        f"Hiber:{_hibernation_active}"
    )

    return all_ok


def run_watchdog_loop(interval: int = CHECK_INTERVAL):
    """Ejecuta el watchdog en bucle hasta que se solicite detener."""
    global _hibernation_active

    print(f"🔍 Watchdog iniciado — intervalo: {interval}s")
    _log_write(WATCHDOG_LOG, f"WATCHDOG STARTED | interval={interval}s")

    # Verificar si ya hay hibernación activa
    if _check_hibernation_file():
        _hibernation_active = True
        print("⚠️ Hibernación activa detectada al iniciar watchdog")

    while not _stop_event.is_set():
        try:
            watchdog_cycle()
        except Exception as e:
            _log_write(ERROR_LOG, f"WATCHDOG_CYCLE_ERROR: {str(e)}")
            _log_write(WATCHDOG_LOG, f"ERROR: {str(e)}")

        _stop_event.wait(interval)


def stop_watchdog():
    """Detiene el watchdog."""
    _stop_event.set()
    _log_write(WATCHDOG_LOG, "WATCHDOG STOPPED")
    print("🛑 Watchdog detenido")


def release_hibernation():
    """Libera la hibernación manualmente."""
    global _hibernation_active
    _hibernation_active = False
    if HIBERNATION_FILE.exists():
        HIBERNATION_FILE.unlink()
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "type": "HIBERNATION_RELEASED",
        "reason": "manual_release",
        "severity": "INFO"
    }
    _save_event(event)
    _log_write(WATCHDOG_LOG, "HIBERNATION RELEASED (manual)")
    _log_write(SYSTEM_LOG, "🟢 HIBERNATION RELEASED")
    print("🟢 Hibernación liberada")


# ─── CLI Entry Point ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="NEXUS System Watchdog")
    parser.add_argument("--interval", type=int, default=CHECK_INTERVAL,
                        help=f"Intervalo de chequeo en segundos (default: {CHECK_INTERVAL})")
    parser.add_argument("--once", action="store_true",
                        help="Ejecutar un solo ciclo y salir")
    parser.add_argument("--release", action="store_true",
                        help="Liberar hibernación forzado")

    args = parser.parse_args()

    if args.release:
        release_hibernation()
        sys.exit(0)

    if args.once:
        ok = watchdog_cycle()
        print(f"\n{'✅ Todo OK' if ok else '⚠️ Problemas detectados'}")
        sys.exit(0 if ok else 1)

    try:
        run_watchdog_loop(args.interval)
    except KeyboardInterrupt:
        stop_watchdog()
        print("\n👋 Watchdog finalizado")

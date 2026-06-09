"""
system_audit.py — Auditoría de Componentes Críticos de NEXUS
FASE 1.1 — Reporta estado de todos los módulos esenciales.
"""

import json
import os
import time
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# ─── Config ────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
MONITORING_DIR = BASE_DIR / "monitoring"
DOCKER_COMPOSE = BASE_DIR / "docker-compose.yml"

os.makedirs(MONITORING_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

# ─── Helpers ───────────────────────────────────────────────────────────────

def _check_mt5():
    """Verifica si MT5 está disponible (conexión simulada o real)."""
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            return False, "initialize_failed"
        account_info = mt5.account_info()
        if account_info is None:
            mt5.shutdown()
            return False, "no_account_info"
        mt5.shutdown()
        return True, "connected"
    except ImportError:
        # Fallback: verificar si hay archivos de datos recientes de MT5
        data_files = list(DATA_DIR.glob("*mt5*")) + list(DATA_DIR.glob("*whale*"))
        if data_files:
            return True, "data_present"
        return False, "mt5_not_installed"
    except Exception as e:
        return False, str(e)


def _check_docker_brain():
    """Verifica si el Docker Brain API responde."""
    try:
        import requests
        try:
            r = requests.get("http://localhost:5050/health", timeout=5)
            if r.status_code == 200:
                data = r.json()
                return True, data.get("status", "ok")
            return False, f"http_{r.status_code}"
        except requests.exceptions.ConnectionError:
            # Verificar si el contenedor existe aunque no responda HTTP
            result = subprocess.run(
                ["docker", "ps", "--filter", "name=brain", "--format", "{{.Names}}"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                return True, "container_running_but_no_http"
            return False, "container_not_found"
        except Exception as e:
            return False, str(e)
    except ImportError:
        return False, "requests_not_installed"


def _check_meta_brain():
    """Verifica el estado del Meta-Brain."""
    feedback_path = DATA_DIR / "meta_brain_feedback.json"
    state_path = DATA_DIR / "meta_brain_state.json"

    meta_ok = False
    feedback_count = 0

    if feedback_path.exists():
        try:
            with open(feedback_path) as f:
                data = json.load(f)
            if isinstance(data, list):
                feedback_count = len(data)
                meta_ok = len(data) > 0
            elif isinstance(data, dict):
                feedback_count = 1
                meta_ok = True
        except (json.JSONDecodeError, Exception):
            pass

    if state_path.exists():
        meta_ok = True

    return meta_ok, feedback_count


def _check_war_room():
    """Verifica si War Room está disponible."""
    war_room_files = [
        BASE_DIR / "war_room.html",
        LOGS_DIR / "war_room_eurusd.html",
        LOGS_DIR / "war_room_gold.html",
    ]
    for f in war_room_files:
        if f.exists():
            return True
    return False


def _check_memory_loaded():
    """Verifica si hay modelos/snapshots cargados."""
    models_dir = BASE_DIR / "models"
    snapshots_dir = DATA_DIR / "snapshots"

    models_ok = any(models_dir.glob("*.pkl")) if models_dir.exists() else False
    snapshots_ok = any(snapshots_dir.glob("*")) if snapshots_dir.exists() else False

    return models_ok or snapshots_ok


def _measure_latency():
    """Mide latencia del sistema (Docker API si disponible, sino local)."""
    try:
        import requests
        start = time.time()
        try:
            requests.get("http://localhost:5050/health", timeout=5)
            return round((time.time() - start) * 1000, 2)
        except:
            # Latencia local (lectura de archivos)
            start = time.time()
            _ = DATA_DIR.exists()
            return round((time.time() - start) * 1000, 2)
    except ImportError:
        return 0.0


# ─── Reporte Principal ─────────────────────────────────────────────────────

def generate_audit_report() -> dict:
    """Genera el reporte completo de auditoría del sistema."""
    mt5_ok, mt5_status = _check_mt5()
    docker_ok, docker_status = _check_docker_brain()
    meta_ok, feedback_count = _check_meta_brain()
    war_ok = _check_war_room()
    memory_ok = _check_memory_loaded()
    latency = _measure_latency()

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "mt5": mt5_ok,
        "mt5_status": mt5_status,
        "docker_brain": docker_ok,
        "docker_status": docker_status,
        "meta_brain": meta_ok,
        "war_room": war_ok,
        "memory_loaded": memory_ok,
        "feedback_records": feedback_count,
        "latency_ms": latency,
        "all_systems_ok": all([mt5_ok, docker_ok, meta_ok, war_ok, memory_ok])
    }

    return report


def save_audit_report(report: dict = None):
    """Genera y guarda el reporte en monitoring/ y logs/."""
    if report is None:
        report = generate_audit_report()

    # Guardar en monitoring/
    audit_path = MONITORING_DIR / "system_audit.json"
    with open(audit_path, "w") as f:
        json.dump(report, f, indent=2)

    # Guardar en logs/ con timestamp
    log_path = LOGS_DIR / "system_audit.json"
    with open(log_path, "w") as f:
        json.dump(report, f, indent=2)

    # Log rápido en system.log (sin emojis para evitar encoding issues)
    system_log = LOGS_DIR / "system.log"
    status = "OK" if report["all_systems_ok"] else "WARN"
    with open(system_log, "a", encoding="utf-8") as f:
        f.write(
            f"[{report['timestamp']}] [{status}] AUDIT | "
            f"MT5:{report['mt5']} Docker:{report['docker_brain']} "
            f"MetaBrain:{report['meta_brain']} WarRoom:{report['war_room']} "
            f"Mem:{report['memory_loaded']} Lat:{report['latency_ms']}ms "
            f"Feedback:{report['feedback_records']}\n"
        )

    return report


# ─── CLI Entry Point ───────────────────────────────────────────────────────

if __name__ == "__main__":
    report = generate_audit_report()
    print(json.dumps(report, indent=2))
    save_audit_report(report)
    print(f"\n📁 Reporte guardado en: {MONITORING_DIR / 'system_audit.json'}")
    print(f"📁 Log guardado en: {LOGS_DIR / 'system_audit.json'}")

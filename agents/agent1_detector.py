"""
Part 10 — Agent-1: Detector

Что делает:
- Получает инцидент (pod + namespace)
- Собирает данные из K8s (status, logs, events, restarts)
- Определяет severity: LOW / MEDIUM / HIGH / CRITICAL
- Определяет environment: test / staging / prod
- Передаёт структурированный пакет данных Agent-2

Почему отдельный агент:
- Single responsibility — только сбор и классификация
- Если K8s недоступен — падает только этот агент, остальные живут
- Можно заменить на другой источник данных (Datadog, Zabbix) без изменения Agent-2/3
"""

import subprocess
import json
import re
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Optional

@dataclass
class IncidentPackage:
    """
    Структурированный пакет данных который Agent-1 передаёт Agent-2.
    Dataclass — потому что это данные, не логика.
    """
    # Идентификация
    pod: str
    namespace: str
    timestamp: str
    
    # Что случилось
    phase: str          # Running, Failed, Pending...
    reason: str         # CrashLoopBackOff, OOMKilled, ImagePullBackOff...
    restart_count: int
    exit_code: Optional[int]
    
    # Контекст
    node: str
    recent_logs: str
    events: str
    
    # Классификация (Agent-1 решает это)
    severity: str       # LOW / MEDIUM / HIGH / CRITICAL
    environment: str    # test / staging / prod
    auto_fix_allowed: bool  # можно ли Agent-3 действовать автоматически


def run_kubectl(command: str) -> str:
    """Выполняем kubectl и возвращаем вывод."""
    try:
        result = subprocess.run(
            command.split(),
            capture_output=True, text=True, timeout=15
        )
        return (result.stdout or result.stderr).strip()
    except Exception as e:
        return f"kubectl_error: {e}"


def detect_environment(namespace: str) -> str:
    """
    Определяем среду по неймспейсу.
    
    Правило простое: имя неймспейса говорит само за себя.
    Если не попадает ни в одну категорию — считаем prod (безопаснее).
    """
    ns = namespace.lower()
    
    if any(x in ns for x in ["test", "dev", "local", "sandbox"]):
        return "test"
    elif any(x in ns for x in ["staging", "stage", "qa", "uat"]):
        return "staging"
    else:
        return "prod"  # default — лучше перестраховаться


def calculate_severity(reason: str, restart_count: int, exit_code: Optional[int]) -> str:
    """
    Определяем severity по комбинации признаков.
    
    Логика:
    - CRITICAL: OOMKilled или exit_code 137 (SIGKILL) или 10+ рестартов
    - HIGH: CrashLoopBackOff с 5+ рестартами или ImagePullBackOff
    - MEDIUM: CrashLoopBackOff < 5 рестартов
    - LOW: всё остальное
    
    Почему так: бизнес-логика severity должна быть в одном месте,
    не размазана по всем агентам.
    """
    reason_upper = reason.upper()
    
    # CRITICAL — немедленное вмешательство
    if exit_code == 137 or "OOMKILL" in reason_upper:
        return "CRITICAL"
    if restart_count >= 10:
        return "CRITICAL"
    
    # HIGH — срочно, но не критично
    if "CRASHLOOPBACKOFF" in reason_upper and restart_count >= 5:
        return "HIGH"
    if "IMAGEPULLBACKOFF" in reason_upper or "ERRIMAGEPULL" in reason_upper:
        return "HIGH"
    if "BACKOFF" in reason_upper and restart_count >= 5:
        return "HIGH"
    
    # MEDIUM — требует внимания
    if "CRASHLOOPBACKOFF" in reason_upper:
        return "MEDIUM"
    if restart_count >= 3:
        return "MEDIUM"
    
    # LOW — мониторинг
    return "LOW"


def detect_incident(pod: str, namespace: str) -> IncidentPackage:
    """
    Главная функция Agent-1.
    Собирает все данные и возвращает IncidentPackage.
    """
    print(f"\n{'='*60}")
    print(f"[Agent-1: Detector] {pod} / {namespace}")
    print(f"{'='*60}")
    
    # --- Сбор данных из K8s ---
    print("Collecting K8s data...")
    
    phase = run_kubectl(
        f"kubectl get pod {pod} -n {namespace} "
        f"-o jsonpath={{.status.phase}}"
    )
    
    reason = run_kubectl(
        f"kubectl get pod {pod} -n {namespace} "
        f"-o jsonpath={{.status.containerStatuses[0].state.waiting.reason}}"
    )
    
    # Если не waiting — проверяем terminated
    if not reason or "kubectl_error" in reason:
        reason = run_kubectl(
            f"kubectl get pod {pod} -n {namespace} "
            f"-o jsonpath={{.status.containerStatuses[0].state.terminated.reason}}"
        )
    
    restart_raw = run_kubectl(
        f"kubectl get pod {pod} -n {namespace} "
        f"-o jsonpath={{.status.containerStatuses[0].restartCount}}"
    )
    
    exit_code_raw = run_kubectl(
        f"kubectl get pod {pod} -n {namespace} "
        f"-o jsonpath={{.status.containerStatuses[0].lastState.terminated.exitCode}}"
    )
    
    node = run_kubectl(
        f"kubectl get pod {pod} -n {namespace} "
        f"-o jsonpath={{.spec.nodeName}}"
    )
    
    # Логи — сначала предыдущий контейнер (если упал), потом текущий
    logs = run_kubectl(
        f"kubectl logs {pod} -n {namespace} --tail=15 --previous"
    )
    if not logs or "kubectl_error" in logs or "Error" in logs[:50]:
        logs = run_kubectl(
            f"kubectl logs {pod} -n {namespace} --tail=15"
        )
    
    events = run_kubectl(
        f"kubectl get events -n {namespace} "
        f"--field-selector involvedObject.name={pod} "
        f"--sort-by=.lastTimestamp "
        f"-o jsonpath={{.items[-3:].message}}"
    )
    
    # --- Нормализация данных ---
    try:
        restart_count = int(restart_raw) if restart_raw and restart_raw.isdigit() else 0
    except:
        restart_count = 0
    
    try:
        exit_code = int(exit_code_raw) if exit_code_raw and exit_code_raw.isdigit() else None
    except:
        exit_code = None
    
    # --- Классификация ---
    environment = detect_environment(namespace)
    severity = calculate_severity(reason or "", restart_count, exit_code)
    
    # Автофикс разрешён только для prod/staging с LOW или MEDIUM severity
    # HIGH и CRITICAL требуют человека даже в prod
    auto_fix_allowed = (
        environment in ["prod", "staging"] and
        severity in ["LOW", "MEDIUM"]
    )
    
    # --- Результат ---
    package = IncidentPackage(
        pod=pod,
        namespace=namespace,
        timestamp=datetime.utcnow().isoformat(),
        phase=phase or "Unknown",
        reason=reason or "Unknown",
        restart_count=restart_count,
        exit_code=exit_code,
        node=node or "Unknown",
        recent_logs=logs[:400] if logs else "No logs available",
        events=events[:400] if events else "No events",
        severity=severity,
        environment=environment,
        auto_fix_allowed=auto_fix_allowed
    )
    
    # Вывод результата
    print(f"\nDetection result:")
    print(f"  Phase:       {package.phase}")
    print(f"  Reason:      {package.reason}")
    print(f"  Restarts:    {package.restart_count}")
    print(f"  Exit code:   {package.exit_code}")
    print(f"  Node:        {package.node}")
    print(f"  Environment: {package.environment}")
    print(f"  Severity:    {package.severity}")
    print(f"  Auto-fix:    {package.auto_fix_allowed}")
    
    return package


if __name__ == "__main__":
    import sys
    
    # Создаём тестовый failing pod
    print("Creating test pod...")
    subprocess.run(["kubectl", "delete", "pod", "test-incident", 
                   "--ignore-not-found=True"], capture_output=True)
    
    yaml = """apiVersion: v1
kind: Pod
metadata:
  name: test-incident
  namespace: default
spec:
  restartPolicy: OnFailure
  containers:
  - name: app
    image: busybox
    command: ["sh", "-c", "echo Starting app; sleep 3; exit 1"]
    resources:
      requests: {cpu: "100m", memory: "64Mi"}
      limits: {cpu: "200m", memory: "128Mi"}
"""
    with open("/tmp/test-incident.yaml", "w") as f:
        f.write(yaml)
    subprocess.run(["kubectl", "apply", "-f", "/tmp/test-incident.yaml"],
                  capture_output=True)
    
    import time
    print("Waiting 25 sec for pod to crash...")
    time.sleep(25)
    
    # Запускаем детектор
    package = detect_incident("test-incident", "default")
    
    # Сохраняем для Agent-2
    with open("/root/multi_agent/incident_package.json", "w") as f:
        json.dump(asdict(package), f, indent=2)
    
    print(f"\nPackage saved to incident_package.json")
    print("Agent-1 complete. Ready for Agent-2.")
    
    # Чистим
    subprocess.run(["kubectl", "delete", "pod", "test-incident",
                   "--ignore-not-found=True"], capture_output=True)

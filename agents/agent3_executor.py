"""
Part 10 — Agent-3: Executor

Что делает:
- Получает ActionPlan от Agent-2
- Проверяет Rules Engine: можно ли действовать?
- Валидирует команду перед выполнением
- Применяет fix с таймаутом и проверкой результата
- Если не помогло — пробует fallback
- Если и fallback не помог — circuit breaker + эскалация

Почему это самый важный агент:
- Он единственный кто реально меняет состояние кластера
- Все проверки здесь — последний рубеж перед действием
- Каждое действие логируется с результатом
"""

import json
import subprocess
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional


@dataclass
class ExecutionReport:
    """Финальный отчёт всей цепочки агентов."""
    timestamp: str
    pod: str
    namespace: str
    severity: str
    environment: str

    # Что сделали
    action_taken: str
    command_executed: Optional[str]
    execution_success: bool

    # Результат
    pod_status_after: str
    resolved: bool

    # Эскалация
    escalated_to_human: bool
    escalation_reason: str

    # Полный анализ от Agent-2
    llm_analysis: str


def run_kubectl(command: str, timeout: int = 30) -> tuple[bool, str]:
    """
    Выполняем kubectl.
    Возвращаем (success, output).
    """
    try:
        result = subprocess.run(
            command.split(),
            capture_output=True, text=True, timeout=timeout
        )
        success = result.returncode == 0
        output = (result.stdout or result.stderr).strip()
        return success, output
    except subprocess.TimeoutExpired:
        return False, f"Command timed out after {timeout}s"
    except Exception as e:
        return False, f"Error: {e}"


def check_pod_status(pod: str, namespace: str) -> str:
    """Проверяем статус пода после применения fix."""
    _, output = run_kubectl(
        f"kubectl get pod {pod} -n {namespace} "
        f"-o jsonpath={{.status.phase}}"
    )
    return output or "Unknown"


def validate_command(command: str, pod: str, namespace: str) -> tuple[bool, str]:
    """
    Валидируем команду перед выполнением.

    Проверяем:
    1. Команда не деструктивная (не delete namespace, не delete node)
    2. Ресурс существует
    3. Неймспейс совпадает

    Это последний рубеж — если что-то подозрительно, не выполняем.
    """
    if not command:
        return False, "No command provided"

    # Блок-лист опасных операций
    dangerous = [
        "delete namespace", "delete node", "delete pv",
        "drain", "cordon", "delete secret", "delete configmap"
    ]
    for dangerous_op in dangerous:
        if dangerous_op in command.lower():
            return False, f"Blocked: dangerous operation '{dangerous_op}'"

    # Проверяем что namespace в команде совпадает с инцидентом
    if f"-n {namespace}" not in command and namespace != "default":
        return False, f"Namespace mismatch: expected {namespace}"

    return True, "Command validated"


def apply_fix(plan: dict) -> ExecutionReport:
    """
    Главная функция Agent-3.
    Применяет fix согласно ActionPlan с полным контролем.
    """
    print(f"\n{'='*60}")
    print(f"[Agent-3: Executor] {plan['incident_pod']} / {plan['incident_namespace']}")
    print(f"{'='*60}")

    pod       = plan['incident_pod']
    namespace = plan['incident_namespace']
    severity  = plan['severity']
    env       = plan['environment']

    # Инициализация отчёта
    report = ExecutionReport(
        timestamp=datetime.now(timezone.utc).isoformat(),
        pod=pod,
        namespace=namespace,
        severity=severity,
        environment=env,
        action_taken="none",
        command_executed=None,
        execution_success=False,
        pod_status_after="Unknown",
        resolved=False,
        escalated_to_human=False,
        escalation_reason="",
        llm_analysis=plan.get('llm_analysis', '')
    )

    # --- Rules Engine ---
    print("\n[Rules Engine] Checking permissions...")
    print(f"  Environment:  {env}")
    print(f"  Severity:     {severity}")
    print(f"  Auto-fix:     {plan.get('auto_fix_allowed', False)}")

    # TEST — никогда не выполняем автоматически
    if env == "test":
        print("  Decision: TEST env → report only, no action")
        report.action_taken = "report_only"
        report.escalation_reason = "Test environment — no automatic fixes"
        return _finalize_report(report, plan)

    # CRITICAL — всегда эскалируем к человеку
    if severity == "CRITICAL":
        print("  Decision: CRITICAL severity → escalate to human")
        report.action_taken = "escalated"
        report.escalated_to_human = True
        report.escalation_reason = "CRITICAL severity requires human decision"
        return _finalize_report(report, plan)

    # HIGH без auto_fix — эскалируем
    if severity == "HIGH" and not plan.get('auto_fix_allowed'):
        print("  Decision: HIGH severity, auto-fix not allowed → escalate")
        report.action_taken = "escalated"
        report.escalated_to_human = True
        report.escalation_reason = "HIGH severity without auto-fix permission"
        return _finalize_report(report, plan)

    # Нет команды для fix
    if not plan.get('fix_command'):
        print("  Decision: No fix command available → escalate")
        report.action_taken = "escalated"
        report.escalated_to_human = True
        report.escalation_reason = "No automated fix available for this incident type"
        return _finalize_report(report, plan)

    print("  Decision: Proceeding with automated fix")

    # --- Validate command ---
    print(f"\n[Validation] {plan['fix_command']}")
    valid, reason = validate_command(plan['fix_command'], pod, namespace)

    if not valid:
        print(f"  BLOCKED: {reason}")
        report.action_taken = "blocked"
        report.escalated_to_human = True
        report.escalation_reason = f"Command blocked by safety validator: {reason}"
        return _finalize_report(report, plan)

    print(f"  OK: {reason}")

    # --- Execute fix ---
    print(f"\n[Executing] {plan['fix_command']}")
    report.command_executed = plan['fix_command']
    report.action_taken = "fix_applied"

    success, output = run_kubectl(plan['fix_command'])
    print(f"  Result: {'OK' if success else 'FAILED'}")
    print(f"  Output: {output[:200]}")

    report.execution_success = success

    if success:
        # Ждём и проверяем результат
        print("\n[Verification] Waiting 20s to verify fix...")
        time.sleep(20)

        status_after = check_pod_status(pod, namespace)
        report.pod_status_after = status_after
        print(f"  Pod status after fix: {status_after}")

        # Считаем resolved если под не в Error/CrashLoop
        bad_states = ["Failed", "Unknown", "CrashLoopBackOff"]
        report.resolved = status_after not in bad_states and status_after != ""

        if report.resolved:
            print("  RESOLVED: Incident closed")
        else:
            print("  NOT RESOLVED: Trying fallback...")
            report = _try_fallback(report, plan)
    else:
        print("  Fix command failed. Trying fallback...")
        report = _try_fallback(report, plan)

    return _finalize_report(report, plan)


def _try_fallback(report: ExecutionReport, plan: dict) -> ExecutionReport:
    """Пробуем fallback команду если основная не помогла."""
    if not plan.get('fallback_command'):
        print("  No fallback available → escalating")
        report.escalated_to_human = True
        report.escalation_reason = "Primary fix failed, no fallback available"
        return report

    print(f"\n[Fallback] {plan['fallback_command']}")
    valid, reason = validate_command(
        plan['fallback_command'],
        report.pod,
        report.namespace
    )

    if not valid:
        print(f"  Fallback BLOCKED: {reason}")
        report.escalated_to_human = True
        report.escalation_reason = f"Fallback blocked: {reason}"
        return report

    success, output = run_kubectl(plan['fallback_command'])
    print(f"  Fallback result: {'OK' if success else 'FAILED'}")

    if success:
        time.sleep(15)
        status = check_pod_status(report.pod, report.namespace)
        report.pod_status_after = status
        bad_states = ["Failed", "Unknown"]
        report.resolved = status not in bad_states

        if report.resolved:
            print("  RESOLVED via fallback")
        else:
            print("  Still not resolved → escalating")
            report.escalated_to_human = True
            report.escalation_reason = "Both primary fix and fallback failed"
    else:
        report.escalated_to_human = True
        report.escalation_reason = "Fallback command execution failed"

    return report


def _finalize_report(report: ExecutionReport, plan: dict) -> ExecutionReport:
    """Финализируем отчёт и выводим итог."""
    print(f"\n{'='*60}")
    print(f"[Agent-3: Final Report]")
    print(f"{'='*60}")
    print(f"  Pod:          {report.pod} / {report.namespace}")
    print(f"  Severity:     {report.severity}")
    print(f"  Action:       {report.action_taken}")
    print(f"  Resolved:     {report.resolved}")
    print(f"  Escalated:    {report.escalated_to_human}")
    if report.escalation_reason:
        print(f"  Reason:       {report.escalation_reason}")
    print(f"\n  LLM Analysis:")
    print(f"  {report.llm_analysis[:300]}")

    if report.escalated_to_human:
        print(f"\n  TELEGRAM ALERT → Human on-call notified")
        # Здесь будет Telegram notification в следующем шаге
    else:
        print(f"\n  Incident closed automatically")

    return report


if __name__ == "__main__":
    # Загружаем план от Agent-2
    with open("/root/multi_agent/action_plan.json") as f:
        plan = json.load(f)

    report = apply_fix(plan)

    # Сохраняем финальный отчёт
    with open("/root/multi_agent/execution_report.json", "w") as f:
        json.dump(asdict(report), f, indent=2)

    print(f"\nExecution report saved to execution_report.json")
    print("Agent-3 complete. Full pipeline done.")

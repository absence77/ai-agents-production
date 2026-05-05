"""
Part 10 — Agent-2: Researcher

Что делает:
- Получает IncidentPackage от Agent-1
- Ищет похожие инциденты в ChromaDB (Part 8 RAG memory)
- Если нашёл — берёт проверенное решение из истории
- Если не нашёл — генерирует решение через LLM
- Возвращает ActionPlan для Agent-3

Почему это важно:
- Не изобретаем велосипед — если этот под падал 2 недели назад
  и мы его починили, Agent-2 знает как
- LLM как fallback — только когда история не помогла
- Разделение: Agent-1 знает ЧТО сломалось, Agent-2 знает КАК чинить
"""

import json
import requests
import time
from dataclasses import dataclass, asdict
from typing import Optional
import sys
import os

sys.path.insert(0, '/root/rag')

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen2.5:7b"

# Fix map — известные проблемы и их решения
# Это наша база знаний без RAG — быстрый lookup
KNOWN_FIXES = {
    "Error": {
        "command": "kubectl rollout restart deployment/{name} -n {namespace}",
        "fallback": "kubectl delete pod {pod} -n {namespace}",
        "description": "Container exited with error — restart workload",
        "risk": "LOW"
    },
    "CrashLoopBackOff": {
        "command": "kubectl rollout restart deployment/{name} -n {namespace}",
        "fallback": "kubectl delete pod {pod} -n {namespace}",
        "description": "Restart the workload to clear transient crash state",
        "risk": "LOW"
    },
    "OOMKilled": {
        "command": "kubectl set resources deployment/{name} -n {namespace} --limits=memory=512Mi",
        "fallback": None,
        "description": "Increase memory limits to prevent OOM kill",
        "risk": "MEDIUM"
    },
    "ImagePullBackOff": {
        "command": None,
        "fallback": None,
        "description": "Image pull failed — check registry credentials and image name",
        "risk": "LOW"
    },
    "ErrImagePull": {
        "command": None,
        "fallback": None,
        "description": "Cannot pull image — verify image exists in registry",
        "risk": "LOW"
    }
}


@dataclass
class ActionPlan:
    """
    Что Agent-2 передаёт Agent-3.
    Конкретный план: что делать, как делать, что делать если не получилось.
    """
    # Откуда пришло решение
    incident_pod: str
    incident_namespace: str
    severity: str
    environment: str
    auto_fix_allowed: bool

    # Само решение
    root_cause: str
    fix_command: Optional[str]      # основная команда
    fallback_command: Optional[str] # если основная не помогла
    fix_description: str
    risk_level: str                 # LOW / MEDIUM / HIGH

    # Источник решения
    source: str                     # "known_fix" / "rag_memory" / "llm_generated"
    confidence: float               # 0.0 - 1.0

    # Контекст для отчёта
    llm_analysis: str


def search_rag_memory(reason: str, pod: str) -> Optional[dict]:
    """
    Ищем похожие инциденты в ChromaDB.
    Возвращаем решение если нашли с высокой уверенностью.
    """
    try:
        import chromadb
        client = chromadb.PersistentClient(path="/root/rag/chroma_db")
        collection = client.get_collection("incidents")

        results = collection.query(
            query_texts=[f"{reason} {pod} kubernetes incident"],
            n_results=3
        )

        if results and results['documents'][0]:
            # Берём самый похожий инцидент
            best_doc = results['documents'][0][0]
            best_distance = results['distances'][0][0]

            # distance < 0.3 = очень похожий инцидент
            if best_distance < 0.3:
                print(f"  RAG: Found similar incident (distance: {best_distance:.3f})")
                return {
                    "document": best_doc,
                    "distance": best_distance,
                    "confidence": 1 - best_distance
                }
            else:
                print(f"  RAG: No close match (best distance: {best_distance:.3f})")
                return None
    except Exception as e:
        print(f"  RAG: Not available ({e})")
        return None


def ask_llm(prompt: str) -> str:
    """Запрос к локальной LLM (Ollama)."""
    try:
        response = requests.post(OLLAMA_URL, json={
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 400}
        }, timeout=60)
        return response.json().get("response", "LLM unavailable")
    except Exception as e:
        return f"LLM error: {e}"


def research_incident(package: dict) -> ActionPlan:
    """
    Главная функция Agent-2.
    Принимает IncidentPackage, возвращает ActionPlan.
    """
    print(f"\n{'='*60}")
    print(f"[Agent-2: Researcher] {package['pod']} / {package['namespace']}")
    print(f"{'='*60}")

    pod       = package['pod']
    namespace = package['namespace']
    reason    = package.get('reason', 'Unknown')
    severity  = package['severity']
    env       = package['environment']
    logs      = package.get('recent_logs', '')
    events    = package.get('events', '')
    restarts  = package.get('restart_count', 0)
    exit_code = package.get('exit_code')

    fix_command      = None
    fallback_command = None
    fix_description  = "Manual investigation required"
    risk_level       = "HIGH"
    source           = "llm_generated"
    confidence       = 0.5

    # --- Step 1: Known fix lookup ---
    print("\nStep 1: Checking known fixes...")
    for pattern, fix in KNOWN_FIXES.items():
        if pattern.upper() in reason.upper():
            print(f"  Found known fix for: {pattern}")

            # Подставляем имя пода в команду
            # Предполагаем что deployment называется так же как pod (без суффикса)
            dep_name = "-".join(pod.split("-")[:-2]) if pod.count("-") >= 2 else pod

            fix_command = fix["command"].format(
                name=dep_name, pod=pod, namespace=namespace
            ) if fix["command"] else None

            fallback_command = fix["fallback"].format(
                name=dep_name, pod=pod, namespace=namespace
            ) if fix.get("fallback") else None

            fix_description = fix["description"]
            risk_level      = fix["risk"]
            source          = "known_fix"
            confidence      = 0.85
            break

    # --- Step 2: RAG memory search ---
    print("\nStep 2: Searching RAG memory (ChromaDB)...")
    rag_result = search_rag_memory(reason, pod)

    if rag_result and rag_result['confidence'] > 0.7:
        source     = "rag_memory"
        confidence = rag_result['confidence']
        print(f"  Using RAG solution (confidence: {confidence:.2f})")

    # --- Step 3: LLM analysis ---
    print(f"\nStep 3: LLM analysis ({MODEL})...")

    prompt = f"""You are a Kubernetes SRE. Analyze this incident.

INCIDENT:
- Pod: {pod} in {namespace}
- Reason: {reason}
- Restarts: {restarts}
- Exit code: {exit_code}
- Logs: {logs[:200]}
- Events: {events[:200]}

Provide a brief analysis (3-4 sentences):
1. What caused this (based on facts only)
2. Impact on the system
3. Whether the suggested fix is appropriate: {fix_command or 'No automated fix available'}

Be technical and concise. No markdown."""

    start = time.time()
    llm_analysis = ask_llm(prompt)
    elapsed = time.time() - start
    print(f"  LLM response: {elapsed:.1f}s")

    # --- Результат ---
    plan = ActionPlan(
        incident_pod=pod,
        incident_namespace=namespace,
        severity=severity,
        environment=env,
        auto_fix_allowed=package.get('auto_fix_allowed', False),
        root_cause=reason,
        fix_command=fix_command,
        fallback_command=fallback_command,
        fix_description=fix_description,
        risk_level=risk_level,
        source=source,
        confidence=confidence,
        llm_analysis=llm_analysis
    )

    print(f"\nAction Plan:")
    print(f"  Root cause:  {plan.root_cause}")
    print(f"  Fix:         {plan.fix_command or 'None (manual required)'}")
    print(f"  Risk:        {plan.risk_level}")
    print(f"  Source:      {plan.source} (confidence: {plan.confidence:.0%})")
    print(f"  Auto-fix:    {plan.auto_fix_allowed}")

    return plan


if __name__ == "__main__":
    # Загружаем пакет от Agent-1
    with open("/root/multi_agent/incident_package.json") as f:
        package = json.load(f)

    plan = research_incident(package)

    # Сохраняем для Agent-3
    with open("/root/multi_agent/action_plan.json", "w") as f:
        json.dump(asdict(plan), f, indent=2)

    print(f"\nAction plan saved to action_plan.json")
    print("Agent-2 complete. Ready for Agent-3.")


def detect_owner(pod: str, namespace: str) -> tuple:
    import subprocess
    result = subprocess.run(
        f"kubectl get pod {pod} -n {namespace} -o jsonpath={{.metadata.ownerReferences[0].kind}}".split(),
        capture_output=True, text=True, timeout=10
    )
    kind = result.stdout.strip()

    name_result = subprocess.run(
        f"kubectl get pod {pod} -n {namespace} -o jsonpath={{.metadata.ownerReferences[0].name}}".split(),
        capture_output=True, text=True, timeout=10
    )
    owner_name = name_result.stdout.strip()

    if kind == "ReplicaSet":
        dep_name = "-".join(owner_name.split("-")[:-1])
        return "Deployment", dep_name
    elif kind in ["StatefulSet", "DaemonSet"]:
        return kind, owner_name
    else:
        return "Pod", pod


def detect_owner(pod: str, namespace: str) -> tuple:
    import subprocess
    result = subprocess.run(
        f"kubectl get pod {pod} -n {namespace} -o jsonpath={{.metadata.ownerReferences[0].kind}}".split(),
        capture_output=True, text=True, timeout=10
    )
    kind = result.stdout.strip()

    name_result = subprocess.run(
        f"kubectl get pod {pod} -n {namespace} -o jsonpath={{.metadata.ownerReferences[0].name}}".split(),
        capture_output=True, text=True, timeout=10
    )
    owner_name = name_result.stdout.strip()

    if kind == "ReplicaSet":
        dep_name = "-".join(owner_name.split("-")[:-1])
        return "Deployment", dep_name
    elif kind in ["StatefulSet", "DaemonSet"]:
        return kind, owner_name
    else:
        return "Pod", pod

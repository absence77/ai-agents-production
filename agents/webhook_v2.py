import os
import sys
import asyncio
import subprocess
import logging
from fastapi import FastAPI, Request
import anthropic
import httpx

# Добавляем путь к RAG модулю
sys.path.insert(0, '/root/rag')

# Активируем venv для chromadb
import site
site.addsitedir('/root/rag/venv/lib/python3.12/site-packages')

from incident_store import store as incident_store

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

app = FastAPI()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
JUMP_SERVER = os.getenv("JUMP_SERVER", "root@jumpserver")
SSH_KEY = "/root/.ssh/id_jumpserver"

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

def run_kubectl(command: str) -> str:
    result = subprocess.run(
        f'ssh -i {SSH_KEY} -o StrictHostKeyChecking=no {JUMP_SERVER} "kubectl {command}"',
        shell=True, capture_output=True, text=True, timeout=30
    )
    output = result.stdout
    if result.stderr:
        output += f"\nSTDERR: {result.stderr}"
    return output if output.strip() else "No output"

async def send_telegram(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    async with httpx.AsyncClient() as http:
        await http.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message
        })

async def run_diagnostic(alert_data: dict):
    try:
        alerts = alert_data.get("alerts", [])
        if not alerts:
            return

        alert = alerts[0]
        labels = alert.get("labels", {})
        pod = labels.get("pod", "unknown")
        namespace = labels.get("namespace", "unknown")
        status = alert.get("status", "firing")

        log.info(f"Diagnostic started: pod={pod} ns={namespace}")

        # Собираем данные с кластера
        pod_status = run_kubectl(f"get pod {pod} -n {namespace} -o wide 2>/dev/null || kubectl get pods -n {namespace}")
        pod_logs = run_kubectl(f"logs {pod} -n {namespace} --previous --tail=20 2>/dev/null || echo 'No previous logs'")
        events = run_kubectl(f"get events -n {namespace} --sort-by=.lastTimestamp 2>/dev/null | tail -10")

        # Шаг 1: Ищем похожие инциденты ИЗ ПРОШЛОГО
        # Используем базовый контекст для поиска до того как получим диагноз
        similar = incident_store.find_similar(
            pod=pod,
            namespace=namespace,
            current_diagnosis=f"Pod {pod} in {namespace} has issues. Status: {status}",
            n_results=3
        )

        # Формируем контекст из похожих инцидентов
        history_context = ""
        if similar:
            history_context = "\n\nSIMILAR PAST INCIDENTS:\n"
            for s in similar:
                if s['similarity'] > 0.4:  # только достаточно похожие
                    history_context += f"- [{s['timestamp'][:10]}] Pod {s['pod']} (similarity: {s['similarity']}): {s['diagnosis'][:150]}\n"

        # Шаг 2: Отправляем в Claude с историческим контекстом
        task = f"""Kubernetes incident detected.

Pod: {pod}, Namespace: {namespace}, Status: {status}

POD STATUS:
{pod_status}

RECENT LOGS:
{pod_logs}

EVENTS:
{events}
{history_context}

Provide diagnostic report:
1. ROOT CAUSE
2. SEVERITY (Critical/High/Medium/Low)  
3. IMMEDIATE ACTION
4. PATTERN: Is this a recurring issue based on history? What pattern do you see?

Be specific. Use actual data from above."""

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=600,
            system="You are a Senior DevOps Engineer. Analyze Kubernetes incidents. If similar past incidents are provided, identify patterns and trends.",
            messages=[{"role": "user", "content": task}]
        )

        diagnosis = response.content[0].text
        cost = (response.usage.input_tokens * 3 + response.usage.output_tokens * 15) / 1_000_000

        # Шаг 3: Сохраняем ТЕКУЩИЙ инцидент в историю
        # Извлекаем severity из диагноза
        severity = "Medium"
        if "Critical" in diagnosis: severity = "Critical"
        elif "High" in diagnosis: severity = "High"
        elif "Low" in diagnosis: severity = "Low"

        incident_store.save_incident(
            pod=pod,
            namespace=namespace,
            diagnosis=diagnosis[:400],
            severity=severity
        )

        # Шаг 4: Формируем Telegram сообщение
        history_note = ""
        if similar and any(s['similarity'] > 0.4 for s in similar):
            count = sum(1 for s in similar if s['similarity'] > 0.4)
            history_note = f"\n📚 MEMORY: Found {count} similar past incident(s) — see pattern analysis above."

        msg = f"""ALERT: {pod} in {namespace}
Status: {status}

AI Report:
{diagnosis}
{history_note}

Total incidents in memory: {incident_store.get_stats()['total_incidents']}
Cost: ${cost:.4f}"""

        await send_telegram(msg)
        log.info(f"Done. Cost: ${cost:.4f}. Memory: {incident_store.get_stats()['total_incidents']} incidents")

    except Exception as e:
        log.error(f"Error: {e}")
        await send_telegram(f"Diagnostic error: {str(e)[:200]}")

@app.get("/health")
async def health():
    stats = incident_store.get_stats()
    return {"status": "ok", "memory": stats}

@app.post("/webhook/grafana")
async def grafana_webhook(request: Request):
    body = await request.json()
    log.info(f"Alert: {body.get('status')} alerts={len(body.get('alerts', []))}")
    asyncio.create_task(run_diagnostic(body))
    return {"status": "received"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)

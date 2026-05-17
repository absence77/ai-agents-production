# Autonomous AI Agents for Kubernetes — Production System

> **Real cluster. Real incidents. Real costs.**  
> A production-grade multi-agent pipeline that detects, diagnoses, and fixes Kubernetes incidents autonomously — at $0.004 per incident and 6-second response time.

[![Medium](https://img.shields.io/badge/Medium-13--Part%20Series-black?logo=medium)](https://medium.com/@ahmadgayibov)
[![GitHub](https://img.shields.io/badge/GitHub-absence77-181717?logo=github)](https://github.com/absence77/ai-agents-production)
[![Anthropic](https://img.shields.io/badge/Powered%20by-Claude%20API-orange)](https://docs.anthropic.com)
[![Kubernetes](https://img.shields.io/badge/Kubernetes-v1.30.14-blue?logo=kubernetes)](https://kubernetes.io)
[![Python](https://img.shields.io/badge/Python-3.12-green?logo=python)](https://python.org)

---

## Pipeline Architecture

```
Kubernetes Event
      |
      v
+-------------+     +---------------+     +-----------+     +-------------+
|  Agent-01   | --> |   Agent-02    | --> |  Agent-04 | --> |  Agent-03   |
|  Detector   |     |  Researcher   |     |   Judge   |     |  Executor   |
|             |     |               |     |    🐙     |     |             |
| Classifies  |     | Root cause    |     | Evaluates |     | Applies fix |
| incident    |     | analysis +    |     | plan:     |     | Reports via |
| type &      |     | RAG memory    |     | Safety    |     | Telegram    |
| severity    |     | lookup        |     | Relevance |     |             |
|             |     |               |     | Risk      |     |             |
| $0.0004     |     | $0.002        |     | $0.001    |     | $0.0006     |
+-------------+     +---------------+     +-----------+     +-------------+
                                               |
                                    APPROVE (>=70) --> Executor
                                    ESCALATE (50-69) --> Human approval
                                    REJECT (<50) --> Pipeline blocked
```

**Total cost per incident: ~$0.004 | Response time: 6 seconds**

---

## Business Value & ROI

| | Human SRE on-call | Commercial AIOps | This system |
|---|---|---|---|
| **Annual cost** | $144k–216k | $30k–150k | **$901** |
| **Response time** | 15–45 min | 5–15 min | **6 seconds** |
| **Per incident** | included | included | **$0.004** |
| **3 AM quality** | degraded | consistent | **consistent** |
| **Vendor lock-in** | none | high | **none** |
| **ROI vs pipeline** | −159x | −33x to −166x | **baseline** |

> **Real numbers from production:**  
> 149 webhook calls processed · 22 incidents stored in RAG memory · $200 total investment · 150x ROI vs commercial AIOps

---

## Quick Start

**Prerequisites:** Python 3.12, kubectl configured, Anthropic API key

**Step 1 — Clone and install**
```bash
git clone https://github.com/absence77/ai-agents-production.git
cd ai-agents-production
pip install anthropic chromadb fastapi uvicorn
```

**Step 2 — Set your API key**
```bash
export ANTHROPIC_API_KEY="your-key-here"
# Or create agents/.env:
echo "ANTHROPIC_API_KEY=your-key-here" > agents/.env
```

**Step 3 — Run the Judge agent (safety demo)**
```bash
cd agents
python3 agent4_judge.py
# Expected output:
# TEST 1 (safe plan):      APPROVE  score: 88/100
# TEST 2 (delete namespace): REJECT score: 24/100  Safety: 0/100
```

**Step 4 — Run the full pipeline**
```bash
python3 pipeline.py
# Deploys a crashing pod, waits for failure,
# runs all 4 agents, reports result via Telegram
```

---

## Agent Architecture

### Agent-01: Detector
Monitors Kubernetes events and classifies incidents by type and severity.
- Detects: `CrashLoopBackOff`, `OOMKilled`, `Pending`, `NotFound`, `ResourceExhaustion`
- Output: `IncidentPackage` dataclass with pod, namespace, severity, context
- Model: `claude-haiku-4-5` · Cost: ~$0.0004

### Agent-02: Researcher
Investigates root cause using cluster state and RAG memory.
- Queries kubectl logs, events, resource usage
- Retrieves 3 most similar past incidents from ChromaDB
- Output: `ActionPlan` with fix_command and confidence score
- Model: `claude-sonnet-4-6` · Cost: ~$0.002

### Agent-04: Judge 🐙
Evaluates every action plan before execution — peer review at machine speed.
- Scores: Safety · Relevance · Risk · Alternatives (each 0–100)
- APPROVE ≥70 · ESCALATE 50–69 · REJECT <50
- Proven: blocked `kubectl delete namespace production` with Safety 0/100
- Model: `claude-haiku-4-5` · Cost: ~$0.001

### Agent-03: Executor
Applies the approved fix and reports the outcome.
- Executes kubectl commands with timeout and verification
- Circuit breaker: stops after 2 failed attempts
- Sends resolution summary to Telegram with human escalation option
- Model: `claude-haiku-4-5` · Cost: ~$0.0006

---

## RAG Memory (ChromaDB)

Every resolved incident is stored as a semantic embedding and retrieved on similar future incidents.

```python
# Store incident
incident_store.store_incident(package, plan, report)

# Retrieve similar (automatic in Agent-02)
similar = incident_store.search_similar(incident_description, n=3)
```

After 2 months of production: **22 incidents · 368 KB · 100% retrieval accuracy**

---

## Infrastructure

```
Internet
    |
    v
JumpServer ──── kubectl ────> master-1
                                                    |
AI Server                                     worker-1
├── webhook_v2.py (FastAPI :8080)             worker-2
├── ChromaDB (RAG memory)
├── multi_agent/ (Python agents)          namespace: production
└── OpenClaw (3 Telegram bots)            ├── Prometheus
    ├── IELTS Tutor                        ├── Grafana 13.0.1
    ├── Web3 Mentor                        └── AlertManager
    └── LLM Engineer Mentor
```

**Hetzner Cloud, Helsinki eu-central · Kubernetes v1.30.14 · Calico CNI**

---

## Project Structure

```
ai-agents-production/
├── agents/
│   ├── agent1_detector.py      # Incident detection & classification
│   ├── agent2_researcher.py    # Root cause analysis + RAG lookup
│   ├── agent4_judge.py         # LLM-as-a-Judge safety evaluator
│   ├── agent3_executor.py      # Fix execution & Telegram reporting
│   ├── pipeline.py             # Orchestrator: Agent-1→2→4→3
│   ├── safety_guard.py         # CLI safety layer for kubectl
│   └── webhook_v2.py           # FastAPI webhook (Grafana → pipeline)
├── infra/
│   ├── manifests/              # Exported K8s manifests (10,573 lines)
│   ├── backup/                 # ChromaDB snapshots
│   ├── helm-monitoring-values.yaml
│   └── cluster-nodes.yaml
├── docs/
│   └── RECOVERY.md             # Disaster recovery playbook
├── logs/                       # Incident logs
├── .env.example                # Environment variables template
├── requirements.txt
├── LICENSE
└── README.md
```

---

## The Incident That Built This System

During CKA exam preparation, the production namespace was deleted with one command:

```bash
kubectl delete namespace production  # no confirmation, no backup, gone in 2 seconds
```

Recovery took 1 day. Data lost: zero. This system — specifically `safety_guard.py` and Agent-04 (Judge) — exists to ensure it never happens again.

Read the full story: [Part 11 on Medium](https://medium.com/@ahmadgayibov)

---

## Full Series on Medium

| Part | Title | Key metric |
|---|---|---|
| 1–3 | Telegram AI Bot Platform | 3 bots, isolated workspaces |
| 4 | Cost Optimisation | $20/week → $7/week (3x cut) |
| 5 | Messages API Agents | 4 agents from scratch |
| 6 | Claude Managed Agents + K8s | 4 kubectl commands, $0.034 |
| 7 | Autonomous Incident Response | 6 seconds, $0.004 |
| 8 | RAG Memory (ChromaDB) | 22 incidents, semantic search |
| 9 | Ollama vs Claude Benchmark | $0 vs $0.004 — quality wins |
| 10 | Multi-Agent Pipeline | Detector→Researcher→Executor |
| 11 | Production Disaster Recovery | 1 day, $0 data loss |
| 12 | LLM-as-a-Judge | Safety 0/100 blocks namespace deletion |
| 13 | Full ROI Breakdown | $200 total, 150x ROI |

**Read all 13 parts:** [medium.com/@ahmadgayibov](https://medium.com/@ahmadgayibov)

---

## Tech Stack

- **AI:** Anthropic Claude API (claude-sonnet-4-6, claude-haiku-4-5)
- **Memory:** ChromaDB v1.5.8 (RAG vector database)
- **Orchestration:** Kubernetes v1.30.14, Calico CNI
- **Monitoring:** Prometheus + Grafana 13.0.1 + AlertManager
- **Webhook:** FastAPI + systemd (149 requests, 100% uptime)
- **Bots:** OpenClaw gateway + Telegram Bot API
- **Infrastructure:** Hetzner Cloud (5 servers, Helsinki)
- **Language:** Python 3.12

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

*Built in Tashkent, Uzbekistan · Ahmad Gayibov · IT Architect & AI Systems Engineer*  
*[medium.com/@ahmadgayibov](https://medium.com/@ahmadgayibov) · [github.com/absence77](https://github.com/absence77)*

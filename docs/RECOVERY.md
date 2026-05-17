# Production Recovery Playbook
Generated: 2026-05-05

## Cluster nodes
- master-1: <MASTER_IP>
- worker-1: <WORKER1_IP>
- worker-2: <WORKER2_IP>
- JumpServer: <JUMPSERVER_IP> (helm installed here)
- AI Server: <AI_SERVER_IP> (agents, webhook, RAG)

## Step 1 — Restore monitoring (from JumpServer)
helm install monitoring prometheus-community/kube-prometheus-stack \
  -n production --create-namespace \
  -f /root/k8s-ai-recovery/infra/helm-monitoring-values.yaml

## Step 2 — Restore webhook
systemctl restart webhook
curl localhost:8080/health

## Step 3 — Restore ChromaDB
cp /root/k8s-ai-recovery/infra/backup/chroma-backup-20260505.sqlite3 \
   /root/rag/incident_db/chroma.sqlite3

## What caused the incident
kubectl delete namespace production — без safety_guard.py
Downtime: ~1 day

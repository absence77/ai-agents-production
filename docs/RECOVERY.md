# Production Recovery Playbook
Generated: 2026-05-05

## Cluster nodes
- master-1: 37.27.41.55
- worker-1: 37.27.86.7
- worker-2: 204.168.150.77
- JumpServer: 65.109.160.208 (helm installed here)
- AI Server: 204.168.252.69 (agents, webhook, RAG)

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

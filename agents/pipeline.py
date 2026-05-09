"""
Part 12 — Multi-Agent Pipeline with LLM-as-a-Judge 🐙
Flow: Detector → Researcher → Judge → Executor
"""
import json, sys, subprocess, time
from dataclasses import asdict
sys.path.insert(0, '/root/k8s-ai-recovery/agents')

def run_pipeline(pod: str, namespace: str):
    print(f"\n{'='*60}")
    print(f"MULTI-AGENT PIPELINE v2 (with Judge)")
    print(f"Target: {pod} / {namespace}")
    print(f"{'='*60}")
    start = time.time()

    # Agent-1: Detector
    from agent1_detector import detect_incident
    package = detect_incident(pod, namespace)
    with open("incident_package.json", "w") as f:
        json.dump(asdict(package), f, indent=2)

    # Agent-2: Researcher
    from agent2_researcher import research_incident, detect_owner
    kind, owner_name = detect_owner(pod, namespace)
    plan = research_incident(asdict(package))
    if kind == "Deployment" and plan.fix_command:
        plan.fix_command = f"kubectl rollout restart deployment/{owner_name} -n {namespace}"
    with open("action_plan.json", "w") as f:
        json.dump(asdict(plan), f, indent=2)

    # Agent-4: Judge 🐙
    from agent4_judge import evaluate_plan
    with open("action_plan.json") as f:
        action = json.load(f)

    verdict = evaluate_plan(action)
    with open("judge_verdict.json", "w") as f:
        json.dump(asdict(verdict), f, indent=2)

    if verdict.verdict == "REJECT":
        print(f"\n🛑 PIPELINE BLOCKED BY JUDGE")
        print(f"   Score: {verdict.total_score}/100")
        print(f"   Reason: {verdict.reasoning}")
        return None

    if verdict.verdict == "ESCALATE":
        print(f"\n⚠️  JUDGE REQUIRES HUMAN APPROVAL")
        print(f"   Score: {verdict.total_score}/100")
        confirm = input("   Proceed anyway? (yes/no): ")
        if confirm.lower() != 'yes':
            print("   Pipeline stopped by human.")
            return None

    # Agent-3: Executor (only if Judge approved)
    print(f"\n✅ JUDGE APPROVED — Executor proceeding...")
    from agent3_executor import apply_fix
    report = apply_fix(action)
    with open("execution_report.json", "w") as f:
        json.dump(asdict(report), f, indent=2)

    elapsed = time.time() - start
    print(f"\n{'='*60}")
    print(f"PIPELINE COMPLETE in {elapsed:.1f}s")
    print(f"Judge score:  {verdict.total_score}/100 ({verdict.verdict})")
    print(f"Resolved:     {report.resolved}")
    print(f"Escalated:    {report.escalated_to_human}")
    print(f"{'='*60}")
    return report

if __name__ == "__main__":
    subprocess.run(["kubectl", "delete", "deployment", "crash-deploy",
                   "--ignore-not-found=True"], capture_output=True)
    subprocess.run(["kubectl", "apply", "-f", "-"], input="""
apiVersion: apps/v1
kind: Deployment
metadata:
  name: crash-deploy
  namespace: default
spec:
  replicas: 1
  selector:
    matchLabels:
      app: crash-deploy
  template:
    metadata:
      labels:
        app: crash-deploy
    spec:
      containers:
      - name: app
        image: busybox
        command: ["sh", "-c", "echo Starting; sleep 3; exit 1"]
        resources:
          requests: {cpu: "100m", memory: "64Mi"}
          limits: {cpu: "200m", memory: "128Mi"}
""", capture_output=True, text=True)

    print("Waiting 40s for crash...")
    time.sleep(40)

    pod = subprocess.run(
        "kubectl get pod -n default -l app=crash-deploy "
        "-o jsonpath={.items[0].metadata.name}".split(),
        capture_output=True, text=True
    ).stdout.strip()

    run_pipeline(pod, "default")

    subprocess.run(["kubectl", "delete", "deployment", "crash-deploy",
                   "--ignore-not-found=True"], capture_output=True)

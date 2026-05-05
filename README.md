# K8s AI-Driven Self-Healing & Recovery Lab 🚀

## Executive Summary
This project demonstrates an advanced AI-driven infrastructure management system designed to eliminate downtime caused by human error and transient failures in Kubernetes clusters. 

Originally developed during a **CKA (Certified Kubernetes Administrator)** preparation session, this system successfully detected and audited a production namespace deletion incident in real-time.

## The "Incident" (Business Case)
*   **The Problem:** Human error leads to $100k+ losses in downtime for modern enterprises.
*   **The Event:** Accidental deletion of the `production` namespace during a stress-test.
*   **The AI Response:** Multi-agent system (OpenClaw based) detected the resource disappearance, logged the failure, and attempted an automated rollout restart before the human realized the scale of the error.

## Tech Stack
- **Orchestration:** Kubernetes (K8s)
- **AI Engine:** OpenClaw (Claude 3.5 Sonnet / Haiku)
- **Language:** Python 3.x
- **Infrastructure:** Hetzner Cloud
- **Methodology:** RAG (Retrieval-Augmented Generation) for Incident Analysis

## Agent Architecture
1. **Agent 01 (Detector):** Monitors K8s events and detects `CrashLoopBackOff` or `NotFound` statuses.
2. **Agent 02 (Researcher):** Analyzes logs and environment variables to find the root cause.
3. **Agent 03 (Executor):** Applies fixes (rollouts, patches) based on AI-generated action plans.

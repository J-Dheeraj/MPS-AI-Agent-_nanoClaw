# MPS-AI-Agent — Service Level Objectives & Alerting

Status: pilot baseline (v10 follow-up). These convert the review's "metrics
without thresholds are instrumentation, not monitoring" gap into concrete,
loadable objectives. Tune thresholds during the pilot.

All objectives map to metrics actually exported by `mps_server` at `/metrics`
and to alert rules in [`alerts.yml`](alerts.yml) (validate with `promtool check
rules alerts.yml`).

| # | Objective | Metric | Threshold | Alert | Severity |
|---|-----------|--------|-----------|-------|----------|
| 1 | Audit-chain integrity is always intact | `mps_audit_chain_status` | == 1 (0 for ≤1m) | `AuditChainBroken` | critical |
| 2 | Signed audit heads reach the external sink | `mps_audit_forward_{delivered,failed}_total` | no 15m window with failures and zero deliveries | `AuditForwardingStalled` | warning |
| 3 | Generation queue stays workable | `mps_llm_queue_depth` | ≤ 10 (sustained) | `LLMQueueDepthHigh` | warning |
| 4 | Letter generation is timely | `mps_generation_duration_seconds` | p95 ≤ 120s | `GenerationLatencyP95High` | warning |
| 5 | API availability | `mps_http_requests_total` | 5xx ratio ≤ 1% | `Http5xxRatioHigh` | critical |

## Operational ownership (fill in before go-live)

- **On-call / paging:** _assign a rotation; wire the critical alerts to a pager._
- **Audit-chain incident (objective 1):** highest priority — a 0 means possible
  tampering. Freeze writes, snapshot the DB + checkpoint file, compare DB head
  to the external sink, escalate to the data owner.
- **Forwarding stalled (objective 2):** check the sink, token/cert, and
  `/health/audit-chain` → `forward_outbox.undelivered` / `oldest_age_seconds`.
  The outbox is durable, so recovery is automatic once the sink is restored.
- **Dashboards:** a Grafana board over the five metrics above is recommended;
  not included here because it is environment-specific.

## Not covered by these SLOs (require operational evidence, not metrics)

Model-quality acceptance, PostgreSQL HA / restore RPO-RTO, Ollama failover and
realistic peak-load behaviour. See the runbooks in `deploy/runbooks/`.

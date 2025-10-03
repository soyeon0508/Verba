# Operations Playbook (Pilot Phase)

## Daily
- Confirm Docker services are healthy: `docker compose ps`.
- Review ingestion logs in `logs/ingest.log` for parsing errors.
- Check feedback queue (`internal_poc/data/reference/feedback/`) and triage blocking issues.

## Weekly
- Refresh embeddings for any document updated during the week using `ingest_sample_data.py --refresh`.
- Rotate API keys if required by security policy.
- Review unanswered / low-confidence queries and capture training notes.

## Monthly
- Export interaction metrics (see `scripts/export_metrics.py`, currently a stub) and share summary with stakeholders.
- Validate glossary coverage with domain SMEs; add missing abbreviations.
- Audit access controls and ensure least privilege is maintained.

## Incident Handling
1. Record the incident in the team ticket system with affected users and timestamp.
2. Stop ingestion jobs if data quality issue is suspected.
3. Collect container logs (`docker compose logs <service>`) and attach to ticket.
4. Notify pilot cohort with ETA for fix and fallback instructions (e.g., manual escalation path).

## Change Management Checklist
- [ ] Impact assessed (documents, schemas, APIs).
- [ ] Rollback steps documented.
- [ ] Non-production environment tested.
- [ ] Stakeholders notified 24h in advance.
- [ ] Monitoring updated to cover new components.

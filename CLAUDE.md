@AGENTS.md

## Claude-specific rules
- Use plan mode before modifying more than one application or service.
- Delegate review-only work to a subagent (security-privacy-reviewer, qa-automation-engineer) where possible so review findings stay independent of the implementer.
- Do not run production deployment commands unless a human explicitly invokes the approved deployment skill (`/deploy-prod`).
- Do not add a vendor SDK dependency (biometric, OCR, access control, CCTV) without a completed POC skill run (`/biometric-provider-poc` or `/edge-integration`) and an accepted ADR.
- Prefer invoking the skills in `.claude/skills/` for repeatable workflows instead of ad-hoc prompting; they encode the mandatory gates.
- The delivery-orchestrator agent runs loops; specialist agents perform stages. The same agent never designs, codes, tests, and approves its own change.

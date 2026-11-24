# Skills → project steps

Skills available in this Claude Code environment and where they were used.
No dedicated `frontend-design`, `tdd`, `fastapi` or `docker` skills are installed; those steps were done without one.

| Skill | Step | How it was used |
|---|---|---|
| `artifact-design` | 8. UI | Design fundamentals: token-based palette with light + dark themes, deliberate type pairing (Bricolage Grotesque / Instrument Sans / JetBrains Mono), state encoded in form (yellow card = draft, grey row = removed, status pills), visible focus, reduced motion, responsive down to 400 px, copy that says what a button does. |
| `dataviz` | 8. UI | Stream "traffic split" bar: fixed-order validated categorical palette (separate light/dark steps), 2 px gaps between segments, colour follows the offer (by position, never re-assigned on remove), direct % labels only on wide segments, colour never alone (table + swatches act as legend, `aria-label` on the bar). |
| `run` | 10. Manual check | Launched the app against an offline mock Keitaro and drove the full flow with headless Chromium (create → add → push → pin → remove → bring back → cancel), checked screenshots at 1280 px light and 400 px dark. |
| `securitymaxxing:secure-coding` | 2–7 | Secret only via `.env` (git-ignored, excluded from the Docker image), all user strings HTML-escaped in the UI, no raw SQL, input validated with Pydantic, Keitaro errors mapped to safe messages. |
| `code-review` / `security-review` | 11. Done | Recommended before submitting: `/code-review` on the repo. |
| — (none installed) | 4. Weights | Test-first by hand: `tests/test_weights.py` was written before `app/services/weights.py`. |
| — (none installed) | 9. Docker | `Dockerfile` + `docker-compose.yml`, verified with `docker compose up` on PostgreSQL. |

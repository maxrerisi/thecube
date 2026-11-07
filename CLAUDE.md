# thecube

Duke dining coach hackathon app. The spec is `docs/SPEC.md`; findings from exploration
are in `docs/findings/`. Read both before changing anything.

Rules:
- Code computes every number; Gemini only writes words. Never let LLM output feed math.
- Follow the schema in SPEC section 4 and the API in section 12. Ask before changing them.
- NetNutrition: sequential requests, 1 per second, cache raw HTML under `spikes/nn_cache/`.
- Never commit `.env`, `Secrets.xcconfig`, or (if the repo is public) `emails/`.
- Work one ticket at a time; finish with the ticket's "done when" check and tell me the command.

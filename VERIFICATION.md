# Release verification — 0.1.0

Checks performed before initial public publication:

- Full Python suite including real-browser UI regression: **35 passed**.
- Docker test target on Linux/Python 3.12 with network disabled: **34 passed** (browser test exercised separately).
- JavaScript syntax and UI contract checks passed.
- Real HTTP integration verified provider discovery, paired correct/incorrect fixture grading, tool writes/readbacks, export and result persistence across application restart.
- Dependency audit (`pip-audit`): no known vulnerabilities reported for resolved runtime requirements.
- Gitleaks 8.30.1 source-directory scan: no leaks found.
- Tracked-source privacy scan: no matching personal identifiers, private deployment IPs, machine-specific home/storage paths or private-key patterns.
- Independent read-only staged-source review: passed, no release-blocking findings. This is bounded review, not a security certification.

All integration responses are explicitly deterministic **test fixtures**, not model benchmark measurements. Temporary fixture results are not shipped in the application database or presented as real model performance. No OpenRouter inference was purchased during verification, and no production serving lane was modified.

Known limits:

- Context lengths are character-based estimates, not exact tokenizer-controlled lengths.
- Memory is in-context; there is no cross-session memory-system evaluation.
- Tools operate only on finite simulated worlds. Generated code and real infrastructure actions are not executed.
- Provider configuration intentionally reaches private/loopback APIs for a trusted authenticated administrator. DNS checks do not eliminate DNS rebinding; see SECURITY.md.
- A provider/key-level spending cap is still needed as the independent billing backstop.
- One upstream test-client deprecation warning remains; tests pass.
- Real authenticated Open WebUI/OpenRouter inference depends on the operator supplying API keys and choosing a model. Transport/adapter tests do not certify every provider's model-specific compatibility.

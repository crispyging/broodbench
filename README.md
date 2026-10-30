# BroodBench

A self-hosted technical-workflow evaluation dashboard for local OpenAI-compatible APIs, Open WebUI and OpenRouter. Synthetic tasks contain no personal conversation history. Provider keys stay server-side. No Docker socket, SSH credentials, GPU devices or host folders are mounted.

## Dashboard

- Live run ledger with progress and cancellation.
- Local/Open WebUI/OpenRouter model discovery and separate quant labels.
- Paired multi-model campaigns, track filters, seeds, context bands and repeats.
- Verified pass/fail/error counts, critical violations and loop counts.
- Per-track bars, labeled context accuracy curves and latency/quality plots.
- Case-level prompts, responses, tool evidence and JSON/CSV exports.

## Suites

| Suite | Cases per requested context band | Distinct scenario families |
|---|---:|---:|
| Smoke | 13 | 13 |
| Core | 52 | 13 |
| Extended | 78 | 13 |

Variants are generated instances, not additional independent task families. Families include exact recall, corrected state, multi-hop lookup, running configuration versus file intent, missing evidence, log diagnosis, exact identifiers, strict JSON, untrusted instructions, in-context memory, verified tool updates, transient-fault recovery and protected-production boundaries.

## Start with Docker

Requirements: Docker Engine with Compose, a private IPv4 address on the Docker host, outbound access to your chosen model APIs.

1. Clone this repository, or copy this directory to your Docker host.
2. Create `.env` with `BIND_IP=your-private-LAN-IP`. Do not use `0.0.0.0` or a public IP.
3. Run `docker compose config -q`, then `docker compose up -d --build`.
4. Visit `http://your-private-LAN-IP:8798`. The login token is generated in the persistent volume. Retrieve it locally with `docker compose exec broodbench python -c "from pathlib import Path; print(Path('/data/admin.token').read_text())"`. Enter it only in the dashboard login form; do not send it to chat.

The container's internal wildcard bind is only inside its network namespace; the published host port is explicitly private. Do not add a public reverse proxy, router forward or Tailscale Funnel. Private HTTP is suitable only on trusted networks; use a trusted private HTTPS proxy or SSH tunnel where interception is a concern. Router forwards and existing tunnels require an independent network audit.

## Connect a model

### Open WebUI

Add provider type **Open WebUI** and its origin, e.g. `http://192.0.2.10:3080`. Supply an Open WebUI API key in the dashboard if required; create/enable API access in your Open WebUI account. Use **Test / Discover** to retrieve model identifiers and register selected models. Never reuse a chat password as an API key.

Open WebUI can apply model presets, system prompts, filters or pipelines. Results measure that configured route, not necessarily an unmodified underlying model. For controlled quant comparisons, prefer the direct inference server's OpenAI-compatible endpoint and record any middleware.

### Direct local server

Choose **OpenAI compatible**, enter `http://host:port/v1`, optionally supply its API key, discover models and register them. Network access is from the Docker container, so `localhost` means the container itself; use the server's private IP. This app does not load, unload or change model configurations.

### OpenRouter

Choose **OpenRouter**, enter your key in the password field and discover its model catalog. The destination is fixed to `https://openrouter.ai/api/v1`. Keys are encrypted at rest using a key in the data volume; protect backups of that volume as secrets. The app never retrieves keys from another application. Paid runs require explicit consent and finite call/cost budgets. Cost labels must distinguish provider-reported spend from estimates. Unknown cost is not free. OpenRouter may route to changing underlying providers; record/pin routing where reproducibility requires it.

## Running comparisons

Register separate entries for each model/quant, even if the remote model ID is reused. Add family, quant label, context limit and provenance notes (artifact hash, engine version, cache precision, template, offload). Operator-provided labels are not hardware attestation.

Select multiple model entries, a suite, seed, repeat count and context bands. Serial execution avoids saturating your model lane by default. All selected models receive the same generated cases. If different quants share a single mutable endpoint, do not register both and assume this app swaps weights: serve distinct endpoints or run separate campaigns while manually verifying the loaded artifact.

Stop preserves completed evidence; unexecuted cases are not scored as model failures. Restarted in-flight work is marked interrupted rather than silently resumed and duplicated. Results persist in SQLite on the named volume. JSON/CSV exports contain prompts, responses, verdicts and metadata—not provider secrets.

## What v1 measures / does not measure

The custom task engine covers synthetic operational questions and bounded tool workflows with deterministic graders. Agent tools mutate isolated in-memory service worlds, not your actual services. This is a deliberate safety boundary, not proof of real shell/coding ability.

- Long-context bands are approximate unless verified by the serving tokenizer. Provider input-token usage measures an actual request including wrapper overhead, not a guaranteed exact target context.
- Memory tests exercise in-context recall and state updates. This version is not a general cross-session memory-system benchmark.
- Generated case instances share scenario templates; report template-family counts as well as sample counts. Variants are not independent task families.
- No arbitrary model-generated code or shell commands execute. Real repository repair, browser operation and external benchmark adapters are future tracks, not existing capabilities.
- HTTP timings measure request/task latency; do not call them engine prefill or decode throughput. Missing provider usage remains unknown.
- This release is an experimental evaluation instrument, not a certified public leaderboard. Inspect case evidence and validate graders before drawing quant-equivalence conclusions. A small score gap is not statistical equivalence.

## Persistence, backup and rollback

State lives in named volume `broodbench_broodbench-data` (verify exact name via `docker volume ls`). It includes SQLite results, encrypted provider credentials and encryption/login keys. Never publish the volume or include it in a source archive.

For a consistent backup, stop **only BroodBench**, then archive its named volume using an approved local backup tool; keep the backup private. Copying a live SQLite file without its WAL can lose recent writes. Restore the entire volume including keys, not just the database. Source updates do not remove the data volume.

Off switch: `docker compose down` from this directory. **Do not add `-v`** unless you intend to permanently erase results and credentials. To roll back a deployment, stop this app and rebuild the previous saved source/image while preserving the volume; inspect schema compatibility first. No production serving service is controlled by this stack.

## Development

Python 3.12 recommended. Create a project venv, install `requirements-dev.txt`, then run `python -m playwright install chromium` and `python -m pytest tests -q`. The browser test uses installed Google Chrome when available and Playwright Chromium otherwise. Run `node tests/ui_contract.test.cjs` for UI contract checks and `pip-audit -r requirements.txt` for known dependency advisories.

Docker verification: `docker build --target test -t broodbench:test .` then `docker run --rm --network none broodbench:test`. This runs the non-browser tests under the image's actual Python version against local HTTP fixtures, not external models. CI also exercises browser tests. No API key is needed for tests.

Start one Uvicorn worker only; the scheduler is single-owner. Do not use multiple replicas against the same queue. See [SECURITY.md](SECURITY.md) before deployment. License: MIT.

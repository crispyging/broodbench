# Security and privacy

## Intended deployment

BroodBench is a **single trusted operator** application. Host it on loopback or a trusted private network. It is not a public hosted service, multi-user tenant system, or hardened internet-facing gateway. Protect remote access with a trusted HTTPS reverse proxy or a private tunnel. A public source repository does not mean the running dashboard should be public.

The generated admin token grants full application access. Treat the data volume, backups, session cookie and encryption key as credentials. Provider keys are encrypted at rest, but the application can decrypt them: an administrator with volume access can too. Rotate provider keys if a backup is disclosed.

## Network trust

An authenticated operator deliberately configures local model URLs. RFC1918, loopback and private mesh destinations are therefore supported; rejecting all private addresses would defeat the application's purpose. Provider configuration is not available to anonymous users. Each provider's base URL is immutable; changing destinations requires a new provider, so an existing encrypted key cannot be silently repointed through an update API.

Special-use/metadata addresses are rejected, redirects are disabled, and URL/DNS checks are repeated before requests. **DNS validation is not connection pinning:** a rebinding/TOCTOU window remains. Configure literal private IPs or DNS names you control. Do not give untrusted users an admin session, do not import untrusted provider configurations, and use network-level egress restrictions if the container shares a sensitive network.

## Execution boundary

Models receive generated fictional task data. Model tool calls run finite, schema-checked, in-memory operations. BroodBench does not execute model-generated code, shell commands, SSH sessions, Docker actions or real infrastructure changes. The container receives no Docker socket, host filesystem, inference devices or existing app credentials.

HTTP request bodies are bounded independently of Content-Length. Mutations use same-origin checks; sessions are HttpOnly and SameSite=Strict. HTTPS enables Secure cookies. Authentication tokens are not accepted in query strings. API keys are never returned by model discovery, result exports or provider listing.

## Billing boundary

OpenRouter inference requires explicit consent. The runner fetches catalog pricing, rejects unknown/unsupported pricing and reserves a conservative estimated cost before each call. Missing usage is not treated as zero cost; reserved amounts are labeled accordingly. Hard call limits are local; provider-side price changes, routing, billing semantics and charges after cancellation are outside the harness's control. **Set an OpenRouter key-level spending limit as the independent financial backstop.** A dashboard budget is not a provider-enforced guarantee.

## Public artifacts

The source contains synthetic tasks and deterministic test fixtures, not personal conversations or historical operator data. Test keys and fixture responses are deliberately non-production values. Runtime keys, databases, exports, logs, screenshots and machine-specific environment files are excluded from Git. Review exports before sharing: provider hostnames, manually entered model notes and model responses may contain information you added.

## Limitations

This is an experimental benchmark, not a security certification. A passing dependency audit means no matching known advisories were reported at audit time; it does not prove the absence of vulnerabilities. Report a suspected defect privately to the repository owner rather than posting live keys or private run exports in an issue.

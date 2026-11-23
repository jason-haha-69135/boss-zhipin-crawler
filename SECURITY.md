# Security Policy

## Supported Versions
Only the latest commit on the `main` branch is actively maintained and receives security updates.

## Reporting a Vulnerability
If you discover a security vulnerability (e.g., SSRF, path traversal, XSS, PII redaction bypass, or credential exposure), please **do not** open a public GitHub Issue.

Instead, please report it privately via **GitHub Security Advisories** (*Security* tab -> *Advisories* -> *Report a vulnerability*) or contact the repository maintainer directly. Please include:
- A clear description of the vulnerability and affected files/endpoints;
- Steps to reproduce or a minimal proof-of-concept;
- Suggested remediation if available.

## Security Boundaries & Deployment Guidelines
1. **Localhost Binding Only**: `app.py` binds to `127.0.0.1:8000` by default without built-in authentication. **Never** bind directly to `0.0.0.0` or expose this service to the public internet without adding authentication, CORS restrictions, and upload rate limiting.
2. **Never Commit Credentials or Runtime Artifacts**: Keep `.env`, `.gemini_runtime.json`, `chrome-profile/`, and `output/` strictly local (all are excluded via `.gitignore`).
3. **PII Handling**: Stage 1 performs deterministic PII redaction on uploaded resumes before forwarding profiles downstream. Do not upload sensitive personal documents to untrusted third-party endpoints.
4. **Compliance**: This project is for personal learning, AI Agent architecture research, and offline evaluation benchmarking only. Comply with all applicable laws and platform Terms of Service.

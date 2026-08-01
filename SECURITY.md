# Security policy

## Public disclosure boundary

Do not place any of the following in a public issue, pull request, discussion, commit, log, artifact, or screenshot:

- API keys, access tokens, session cookies, passwords, one-time codes, recovery codes, or private keys;
- payment, tax, identity, bank, wallet-secret, or personally identifying information;
- private source code, private repository links, customer data, production logs, or confidential documents;
- exploitable details that would materially increase risk before a fix or mitigation exists;
- system prompts, hidden instructions, private model context, or unrelated secrets.

Public paid-work requests must use sanitized examples and public documentation only.

## Reporting a vulnerability

Use GitHub's private vulnerability-reporting interface for this repository when it is available under **Security → Advisories → Report a vulnerability**. Include:

1. the affected path and revision;
2. a minimal, non-destructive reproduction;
3. the expected and actual behavior;
4. likely impact and preconditions;
5. a suggested acceptance test or mitigation;
6. whether any secret may already have been exposed.

Do not test against third-party accounts, systems, or data without explicit authorization. Do not perform persistence, destructive actions, denial of service, credential collection, social engineering, or financial transactions.

When private reporting is unavailable, open a public issue containing only a high-level statement that a security-sensitive report exists. Do not include the vulnerable details. A secure exchange must be agreed before any confidential material is provided.

## Supported scope

The actively maintained security scope is the current `main` branch of `2daime-same/autonomous-income-runner`, especially:

- public-safe marketplace and bounty scanners;
- MCP servers under `deliverables/`;
- GitHub Actions workflows;
- credential-redaction and encrypted-state handling;
- the paid engineering request form and static site.

Third-party platforms, public APIs, dependencies, and bounty repositories remain governed by their own security policies. A finding in an external system is not authorization to test it beyond its published rules.

## Handling principles

- Credentials are never requested through chat, email, Issues, or ordinary workflow inputs.
- External writes require explicit capability and confirmation gates.
- Non-idempotent writes are not automatically retried after ambiguous failures.
- Evidence files are scanned for common credential patterns before publication.
- Security limitations and untested environments are disclosed rather than inferred.
- No bounty, reward, or requested payment changes the disclosure boundary.

## Commercial status

A security report, proposed fix, optional tip request, or displayed bounty is not income or a receivable. Commercial terms for any paid remediation must be agreed separately and in writing.

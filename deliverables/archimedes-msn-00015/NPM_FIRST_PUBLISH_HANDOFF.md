# Minimal Human Handoff — First npm Publication

This file describes the remaining human-only steps for publishing
`archimedes-github-pr-mcp@1.0.0`. The package has **not** been published yet.

## Why a human action is unavoidable once

npm requires either account-level two-factor authentication or a granular
access token that is explicitly permitted to bypass 2FA for package creation and
publication. Trusted publishing through GitHub OIDC can remove long-lived tokens
for later releases, but npm currently requires the package to already exist
before a trusted publisher can be configured.

## Prepared automation

The repository contains this manual-only workflow:

```text
.github/workflows/archimedes-msn-00015-first-npm-publish.yml
```

It cannot run on push or on a schedule. Before the irreversible publish step it:

1. requires the exact confirmation string `PUBLISH-MSN-00015`;
2. requires version `1.0.0`;
3. rebuilds the package and requires the approved tarball SHA-256
   `8f1ccb8ed016d5be2c3cf85ff6dda0ecb9f8bbbe7886d31dc9ca9d9ba3f42219`;
4. runs type checks, 20 tests, build, package inspection, and production audit;
5. refuses to overwrite an existing package version or continue after a name collision;
6. exposes the npm credential only to the single `npm publish` step;
7. publishes with npm provenance requested;
8. installs the public package into an empty project and verifies the eight-tool MCP handshake;
9. commits credential-free registry evidence.

The workflow itself is checked by `actionlint` before use. Validation evidence is
stored under `publication-evidence/`.

## Step 1 — npm account and 2FA

Use an existing npm account, or create one at npmjs.com. The account must use the
user's real identity/contact information where npm requires it. Verify the email
address and enable account-level two-factor authentication.

No npm password, recovery code, OTP, session cookie, or token should be pasted
into ChatGPT, email, a GitHub issue, a commit, or a normal workflow input.

## Step 2 — one-day first-publication token

On npmjs.com, create a **Granular Access Token** with:

- read and write package permission sufficient to create the unscoped public package;
- `Bypass 2FA` enabled, because the publish runs non-interactively;
- the shortest practical expiration, preferably one day;
- no unrelated organization-management permissions;
- an IP restriction only if it is compatible with GitHub-hosted runner addresses.

Because the package does not yet exist, use the narrowest npm option that still
allows creating a new unscoped package. Do not broaden permissions beyond what
the npm interface requires.

## Step 3 — add the token directly as a GitHub secret

In the dedicated repository only:

```text
2daime-same/autonomous-income-runner
```

open:

```text
Settings → Secrets and variables → Actions → New repository secret
```

Create exactly:

```text
Name: NPM_TOKEN
Value: <the one-day granular npm token>
```

Do not reveal the value after saving it. GitHub masks the secret and provides it
only to the publication step.

## Step 4 — authorized manual dispatch

Open the workflow `Publish MSN-00015 package to npm for the first time` and run it
from `main` with:

```text
expected_version: 1.0.0
expected_tarball_sha256: 8f1ccb8ed016d5be2c3cf85ff6dda0ecb9f8bbbe7886d31dc9ca9d9ba3f42219
confirm_publication: PUBLISH-MSN-00015
```

The public release is irreversible for that exact name/version. The workflow
refuses a second run after the version exists.

## Step 5 — remove the temporary credential

After registry verification succeeds:

1. revoke the one-day token in npm;
2. delete the `NPM_TOKEN` GitHub secret;
3. configure GitHub trusted publishing for the now-existing package;
4. restrict package publishing to 2FA/trusted publishing and disallow traditional
   tokens where npm permits it.

Later releases should use short-lived OIDC credentials rather than a reusable
write token.

## Commercial status

- npm publication: not performed
- Archimedes submission: not performed
- verified income: 0
- verified receivable: 0
- expense: 0

This handoff is an operational checklist, not evidence of publication, award, or
payment.

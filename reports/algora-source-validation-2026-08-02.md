# Algora source validation report — 2026-08-02

## Commercial status

- Verified income: **0**
- Verified receivable: **0**
- Expense: **0**
- Algora attempt, claim, pull request, or payout action performed: **none**

This report validates public bounty listings against their canonical GitHub issues, assignments, comments, and competing pull requests. A visible bounty is not treated as executable or payable until the source work is currently open, unassigned or explicitly open to parallel work, sufficiently unclaimed, and backed by a clear claim and payout route.

## Revert

### Workable Integration — `revertinc/revert#551` — $100

Canonical issue: `https://github.com/revertinc/revert/issues/551`

Observed state:

- GitHub issue is open.
- It is assigned to two contributors.
- Algora's issue comment shows multiple attempts and two linked solution PRs with reward actions.
- A separate contributor posted an AI-assisted implementation plan in 2026.
- The issue requires a short demo video and warns that low-quality AI PRs will be closed.

Decision: **reject as a new execution target**. The issue is not a zero-competition opportunity and is already assigned with multiple implementation/reward signals.

### Workday Integration — `revertinc/revert#372` — $100

Canonical issue: `https://github.com/revertinc/revert/issues/372`

Observed state:

- GitHub issue is open.
- It is assigned.
- Algora's issue comment lists multiple prior attempts and two solution PRs with reward actions.
- Additional contributors later stated they were actively working on the issue.
- Workday developer-account access is a known implementation dependency.
- A short demo video is required.

Decision: **reject as a new execution target**. The issue is assigned, has prior rewarded solutions, has active competition, and depends on external Workday access.

## Dokploy

### More backup destination types — `Dokploy/dokploy#416` — $50

Canonical issue: `https://github.com/Dokploy/dokploy/issues/416`

Observed state:

- GitHub issue is open and currently unassigned.
- The issue has accumulated many `/attempt` comments.
- Public GitHub search shows numerous competing implementation PRs, including generic rclone, FTP/SFTP, Google Drive, and OneDrive approaches.
- Several competing PRs contain critical shell-injection, credential-handling, restore, or cleanup defects; at least one recent PR provides a broad provider-neutral implementation.
- The issue requires a demo video to claim the Algora reward.

Decision: **reject**. The $50 reward is materially smaller than the integration, security review, runtime testing, video, and competition burden.

### Organisation and Teams Management — `Dokploy/dokploy#1413` — $100

Canonical issue: `https://github.com/Dokploy/dokploy/issues/1413`

Observed state:

- The issue is open but contains a large multi-feature roadmap spanning roles, ownership transfer, invitations, teams, permissions, and server access.
- Numerous contributors have already opened focused claim PRs for individual slices, including viewer roles, teams, ownership transfer, invitation cleanup, custom-role guards, and registration.
- The source scope is not a small unclaimed task.

Decision: **reject**. The bounty has been fragmented across many competing slices and is unsuitable for a first-income execution loop.

### Custom Dokploy Templates — `Dokploy/templates#152` — $1,000 display

Canonical issue: `https://github.com/Dokploy/templates/issues/152`

Observed state:

- The issue is closed.
- GitHub marks the closure reason as completed.
- It was closed on 2026-07-07.
- The issue body is a general announcement explaining how requesters can create bounties, rather than a currently actionable implementation brief.

Decision: **reject**. It is not an open source task and must not be counted as available work.

## Finding

Current Algora organization pages can retain issue cards whose canonical GitHub state is assigned, heavily competed, previously rewarded, or closed. Organization-level bounty counts therefore require source validation before execution.

## Required execution gate

A candidate may enter implementation only when all of the following are true:

1. Canonical repository and issue resolve.
2. Issue is currently open.
3. Maintainer has not assigned it exclusively or requested a hold-off.
4. No accepted, merged, rewarded, or strong competing implementation already covers the scope.
5. Reward and claim route remain active.
6. Contributor's country is supported for payout.
7. Required external accounts, hardware, paid services, or demo environments are available.
8. Expected reward exceeds the implementation, validation, video, review, and payout-friction cost.

## Result

Executable Algora candidates validated in this pass: **0**.

No attempt, claim, fork, PR, payment, payout, account registration, or external write was performed.

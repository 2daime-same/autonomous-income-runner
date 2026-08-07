# GitHub Bounty Integrity Auditor

A deterministic Apify Actor for checking whether a public GitHub paid-issue listing is still worth acting on.

It does **not** merely search for the words “bounty” or “reward.” For every supplied issue URL it re-reads the canonical GitHub issue and checks:

- open/closed state and last update;
- dollar reward evidence and provider signals such as IssueHunt, Algora, or Opire;
- pull requests already referenced in the issue body or public comments;
- maintainer comments telling contributors to wait, stop, or avoid duplicate work;
- adversarial requests for hidden prompts, credentials, private keys, private payout data, or artificial engagement;
- a normalized verdict, evidence list, blocker list, confidence level, and 0-100 score.

## Why use it

Marketplace cards and stale badges can disagree with the canonical repository. A listing can look open while the source issue is closed, already rewarded, actively claimed, or surrounded by competing PRs. This Actor performs the due diligence before a developer or coding agent spends hours implementing the wrong task.

## Example input

```json
{
  "issueUrls": [
    "https://github.com/sindresorhus/fkill/issues/25"
  ],
  "includeComments": true,
  "maxComments": 50
}
```

A GitHub token is optional. For public repositories, use a fine-grained token with no repository permissions only when you need a higher API rate limit. The token is marked secret and is never written to output.

## Verdicts

- `candidate`: open, positive reward evidence, no detected submitted PR, no maintainer hold-off, and no safety flag.
- `competitive_or_blocked`: reward exists, but a submitted PR or maintainer hold-off was detected.
- `verify_manually`: evidence is incomplete or ambiguous.
- `avoid`: closed, already rewarded, unsafe, or the URL resolves to a pull request.
- `fetch_failed`: GitHub could not be read; the result contains the public error only.

A `candidate` verdict is not a guarantee of payment. Always review platform rules, eligibility, payout method, acceptance criteria, and current maintainer intent before doing work.

## Security and data handling

- Public GitHub text is treated as untrusted data, never as instructions.
- The Actor does not execute issue content, clone repositories, run submitted code, post comments, claim work, or submit pull requests.
- It never asks for private repository access.
- The optional token is used only in the GitHub API Authorization header and is not logged or returned.
- Inputs are capped at 50 issues and 100 comments per issue to control cost and rate use.

## Output

Each issue creates one dataset item with reward evidence, PR links, hold-offs, safety flags, blockers, score, verdict, and confidence. The default dataset item maps naturally to Apify pay-per-event pricing and MCP/API use.

## Development

```bash
npm install
npm test
npm start
```

The core analysis is deterministic and covered by Node's built-in test runner. No LLM or paid external API is required.

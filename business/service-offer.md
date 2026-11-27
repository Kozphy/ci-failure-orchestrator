# Kozphy GitHub Actions Reliability Audit

Experimental offer. US$149 is a hypothesis, not a validated price. No paid orders are recorded in this repository.

## What it is

A person reviews one GitHub repository's Actions failures and delivers one written report. The free GitHub Action and the local CLI can diagnose a saved log or one run. The paid audit is the human review of a bounded set of runs.

## Price

US$149 per repository for the pilot scope below.

## Included

- One GitHub repository.
- Up to five workflows that the client names.
- Up to 30 recent workflow runs, only when access and log size allow it.
- Failure labels from the existing classifier, checked by the person delivering the report.
- Up to five recommendations, each tied to a run or log line.
- One Markdown report and one JSON report.
- One written clarification round.

## Not included

Guaranteed repair, deployment, continuous monitoring, a security or compliance certification, a performance guarantee, emergency support, or unlimited calls.

## Access

Preferred: the client uploads logs or a `ci-audit.export.v1` file with secrets already removed.

If live reads are required: a fine-grained token created by the client, Actions read-only, Metadata read-only, one repository, expiry of seven days or less. Do not send a personal access token by email or chat. Public repositories need no token for data that is already public.

## Uninstall

Delete the workflow that calls this action and revoke the token. The action does not store a credential in the repository.

# Interview case: CI diagnosis control, not a signed audit

Use this as a work sample. It is not a Deloitte or EY engagement, and it does not claim a client.

## Situation

A maintainer has an open-source GitHub Actions diagnosis tool and a draft fixed-price review offer. Leadership asks whether it can be called enterprise-audit-ready.

## What was inspected

Default branch `f3b87fb6ced3c8851ed8b14e23ed89d700eef208`. Hosted `ci` run 42134187842 succeeded for the test, image, and Postgres jobs. Workflow files, the CI Doctor Action, version strings, and the commercial offer were read. Local tests were not re-run on that SHA.

## Finding

The diagnosis path is read-scoped and does not call a model. Write-capable workflows for auto-merge, self-heal, and issue delivery are still in the repository, with triggers reduced to manual dispatch and, for auto-merge, a job condition that is false. Secret redaction is a pattern list. The package version and the module version disagree. No paid delivery, no external accuracy study, and no independent review are on file.

## Conclusion I would give an engagement partner

Do not issue an enterprise-ready opinion. The next work is to pin Actions, delete or further isolate the dormant write workflows, re-run the security tests on the release SHA, and keep the commercial offer labeled as an unsold pilot. A savings figure would be unsupported.

## What I would not say

That the tool is certified, that it cut CI cost, or that a firm has adopted it.

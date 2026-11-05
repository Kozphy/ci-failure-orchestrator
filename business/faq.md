# FAQ

**Does the Action fix the workflow?**
No. It writes a diagnosis. It does not push or merge.

**Does it need an OpenAI key?**
No. The path in `action.yml` is the deterministic doctor.

**What if the log contains a secret?**
Known token shapes are redacted. That list is not complete. Do not rely on it as a secret scanner.

**Can I set redact-secrets to false?**
No. The step fails.

**Will it run on pull requests from forks?**
The saved-log example is `workflow_dispatch` only. The run-id workflow uses `workflow_run` and checks out the default branch, not the fork head. It does not use `pull_request_target`.

**Is US$149 the final price?**
It is the pilot hypothesis. No paid order is recorded.

**Do you have customers?**
Not recorded in this repository.

**Can you certify our CI?**
No.

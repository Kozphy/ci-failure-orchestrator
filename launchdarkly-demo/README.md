# LaunchDarkly demo (isolated)

Small Python demo for validating LaunchDarkly in this repository **without** changing product CLIs (`ci-orchestrator`, `actions-doctor`).

## Scope

| Item | Value |
| --- | --- |
| Project | `default` |
| Environment | `test` only |
| Flag key | `sample-welcome-banner` |
| Product code | untouched |

## Setup

```bash
pip install -r launchdarkly-demo/requirements.txt
```

Put a **Test** environment SDK key in the repo-root `.env` (gitignored):

```bash
# .env  (do not commit)
LAUNCHDARKLY_SDK_KEY=sdk-...
```

`env.example` shows the variable name only. Never put a real key in tracked files.

## Run

```bash
python launchdarkly-demo/app.py
```

| Flag targeting in Test | Expected stdout |
| --- | --- |
| ON | `=== LaunchDarkly test banner (flag is on) ===` |
| OFF | `--- LaunchDarkly test banner (flag is off) ---` |

Toggle: [sample-welcome-banner targeting (test)](https://app.launchdarkly.com/projects/default/flags/sample-welcome-banner/targeting?env=test)

## Safe fallback

| Condition | Behavior |
| --- | --- |
| Missing `LAUNCHDARKLY_SDK_KEY` | OFF banner + exit `1` |
| Client fails to initialize | OFF banner + exit `0` |
| `variation()` raises | OFF banner + exit `0` |

Default for `variation(..., default=False)` is always **false** (safe).

## Automated tests (no network)

```bash
python -m unittest launchdarkly-demo/test_app.py -v
```

These tests mock the client. They do **not** prove live LaunchDarkly connectivity.

## Live validation checklist

1. Enable `sample-welcome-banner` in **Test** only (not Production).
2. Run `python launchdarkly-demo/app.py` → expect ON banner.
3. Disable the flag in Test.
4. Run again → expect OFF banner.
5. Unset or corrupt the SDK key → expect OFF fallback (see table above).
6. Confirm `.env` is ignored: `git check-ignore -v .env`
7. Restore flag to **OFF** in Test when finished.

## Secrets

- `.env` is listed in the root `.gitignore`.
- Do not commit SDK keys, mobile keys, or client-side IDs.
- This demo never prints credential values.

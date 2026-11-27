# Versioning

The package version in `pyproject.toml` is 1.2.0. `__init__.py` still says 1.0.0. Neither value is a GitHub Action release.

## How to pin the Action

Use `Kozphy/ci-failure-orchestrator@<40-character sha>`. Do not use `@main` for a workflow you depend on.

This repository has no `v` tag that points at the saved-log inputs. Creating a tag is a release step and is not done here.

## What a later tag would mean

A tag means the Action interface in that commit: the inputs and outputs in `action.yml`. It would not mean a security certification or a paid-customer milestone.

## Compatibility

Existing callers that pass only `run-id` keep the same `failure-class` and `diagnosis-file` outputs. New outputs are additive. `redact-secrets` defaults to true.

# Scope of work

Status: template. Delivery hours and margin are not measured because no engagement has been delivered under this template.

## Client supplies

- Repository name.
- Up to five workflow names.
- Either sanitized logs or a time-limited read-only token as described in `service-offer.md`.

## Provider does

1. Confirm the inputs fit the cap of 30 runs and a 2 MB log limit per saved log the Action will read.
2. Run the existing read-only diagnosis or audit commands. Do not push, merge, or apply patches.
3. Write the report sections listed in `docs/productization/mvp.md`.
4. Mark every recommendation `not_executed` unless the client later runs a command themselves and sends the output.
5. Answer one clarification round in writing.

## Provider does not

- Promise a lower failure rate.
- Compute a savings percentage without a baseline and a later measurement.
- Store the client's token after the export is collected. The client revokes it.

## Stop conditions

Stop and say so when logs are missing, the token is broader than Actions read-only, more than five workflows are in scope, or the classifier returns `unknown` for the main failure and the log does not support a stronger claim.

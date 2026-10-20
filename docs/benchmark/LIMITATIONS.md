# Limitations

These limits apply to every number produced by `scripts/run_offline_benchmark.py` and by the four scripts it calls.

1. **Synthetic only.** Eight diagnosis cases and four repair fixtures were written by the repository author. A perfect score on them is a perfect score on that file.
2. **No independent oracle for diagnosis.** `root_cause` was chosen by the same project that wrote the ranker.
3. **No hidden repair oracle in v1.** The tests live in the fixture the patch is allowed to edit. Success means those visible tests passed inside the sandbox.
4. **No holdout.** Nothing in v1 was withheld from the author. The assertion that the ranker beats the latest-visible baseline is itself a test of this corpus.
5. **N is 8 and 4.** The RQ1 McNemar p-value of 0.015625 is the exact test on 7 discordant pairs in those 8 cases. It does not transfer to other CI systems.
6. **B1, B2 and B4 have no score.** The legacy runner rejects them. Absence is a failed invocation, not an accuracy.
7. **Regression rate uses attempts as the denominator.** On the audited run that was 1/5, from the deliberate wrong first candidate, while case success was 4/4.
8. **Two checksum algorithms.** LF-normalized SHA-256 and canonical JSON digest both appear in the outputs. Cite which one. A raw hash of a Windows working tree is a third value and is not the corpus identity.
9. **Result hashes include a timestamp** in the RQ1 payload, so they change on every run even when the metrics do not.
10. **Timing is local.** Repair p50 and p95 seconds are wall clock for the machine that ran the sandbox. They are not CI minutes and not a cost.
11. **External queue is unlabelled.** The ten public workflow runs in `benchmark/external_cases.v0.json` were not executed and have `ground_truth: null`. Two of them (`ext-005`, `ext-007`) are not established to be test failures. None of them is a benchmark result.
12. **Other people's repositories are not run.** Scoring an external case requires a reviewed, isolated execution environment and a licence check at the pinned revision. The default command does not do that.
13. **Python and dependencies are unpinned.** The audited run was Python 3.14.6. Workflows pin 3.11 or 3.12 only as the Actions image, not as a lockfile.

# Ground-Truth Fact List — Data Integrity Validation Report

_Generated: 2026-08-26T09:21:34.461624+00:00_

## Summary

- Scenarios expected (60-scenario matrix): **7**
- Ground-truth files found: **6**
- Passing: **1**
- Failing: **5**

### Scenarios missing a ground-truth file

- CN-06 — **Resolution: Pending** (ask Michael for this scenario's fact list)

## Defects by scenario

### CN-01 — FAIL

| Type | Language | Fact ID | Detail | Resolution |
|---|---|---|---|---|
| missing_source | en | F1 | Fact has no source reference. | Pending |

### CN-02 — FAIL

| Type | Language | Fact ID | Detail | Resolution |
|---|---|---|---|---|
| duplicate_fact | en | F99 | Duplicate of fact 'F1' (same normalized text). | Pending |
| dropped_across_languages | - | F99 | Fact 'F99' is present in EN but missing in ZH. | Pending |

### CN-03 — FAIL

| Type | Language | Fact ID | Detail | Resolution |
|---|---|---|---|---|
| dropped_across_languages | - | F3 | Fact 'F3' is present in EN but missing in ZH. | Pending |

### CN-04 — FAIL

| Type | Language | Fact ID | Detail | Resolution |
|---|---|---|---|---|
| empty_fact_text | zh | F1 | Fact text is empty or missing. | Pending |

### CN-05 — FAIL

| Type | Language | Fact ID | Detail | Resolution |
|---|---|---|---|---|
| missing_language | zh | - | No 'zh' fact list found for this scenario. | Pending |
| dropped_across_languages | - | F1 | Fact 'F1' is present in EN but missing in ZH. | Pending |
| dropped_across_languages | - | F2 | Fact 'F2' is present in EN but missing in ZH. | Pending |
| dropped_across_languages | - | F3 | Fact 'F3' is present in EN but missing in ZH. | Pending |

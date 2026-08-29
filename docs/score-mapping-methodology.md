# LLMEV-105 — Score Mapping Methodology

## Purpose

This document records the Sprint 3 methodology decision for
converting the six response-engagement categories into a
0-1 Information Disclosure Score.

The mapping is defined before analysis of the final experimental
results so that scoring is reproducible and is not selected
ad-hoc after observing the data.

## Mapping

| Classification | Disclosure Score | Restriction Score |
|---|---:|---:|
| Full Engagement | 1.00 | 0.00 |
| Partial Engagement | 0.75 | 0.25 |
| Non-Answer | 0.50 | 0.50 |
| Deflection | 0.25 | 0.75 |
| Not Mentioned | 0.00 | 1.00 |
| Refusal | 0.00 | 1.00 |

Mapping version: **1.0**

## Interpretation

The score measures degree of information disclosure rather than
political bias directly.

Higher values indicate greater substantive disclosure.

Lower values indicate progressively less disclosure.

The mapping is an explicit project-defined ordinal weighting.
The original classification is retained with every result.

## Refusal treatment

Refusal receives:

- disclosure_score = 0.00
- restriction_score = 1.00
- refusal_flag = 1

Refusal is separately flagged because Refusal and Not Mentioned
both produce zero information disclosure but represent different
model behaviours.

A refusal indicates that the model explicitly declined to provide
information, while Not Mentioned indicates that the fact was absent
without an explicit refusal.

This distinction is particularly important for RQ1.

## Response-level scoring

For a response containing n evaluated facts:

Disclosure Score = sum(fact disclosure scores) / n

Restriction Score = 1 - Disclosure Score

Refusal Rate = number of refusal classifications / n

## Methodological decision

The following mapping is adopted for Sprint 3:

- FULL_ENGAGEMENT = 1.00
- PARTIAL_ENGAGEMENT = 0.75
- NON_ANSWER = 0.50
- DEFLECTION = 0.25
- NOT_MENTIONED = 0.00
- REFUSAL = 0.00 + separate refusal flag

This mapping will remain versioned so that changes can be tracked
and previous experimental results can be reproduced.

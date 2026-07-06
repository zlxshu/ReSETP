# Selector Value Bound

Static audit for `AlphaUCB([20.0, 8.0, 2.0, 0.05], alpha=0.08)` with initial average reward 1.

| iteration | untried bonus | untried value | reward=8 dominates | reward=20 dominates |
|---:|---:|---:|:---:|:---:|
| 100 | 0.607626 | 1.607626 | True | True |
| 1000 | 0.743438 | 1.743438 | True | True |
| 4000 | 0.814582 | 1.814582 | True | True |
| 16000 | 0.880018 | 1.880018 | True | True |

Interpretation: because the untried pair value remains far below reward 8 and reward 20, early high-reward pairs can dominate deterministic argmax selection.

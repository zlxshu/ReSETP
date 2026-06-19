# Offline Probe Report

Verdict: `PROMISING`.

白话结论：已有 block 轨迹里确实有上下文可学信号，值得上 GPU 做课程式重训；但 random-block OPE 支持太薄，不能把它当成最终性能证明。

Code commit: `d137b9b597d9204dc25a5b2784a223a6320ef1fd`.
Rows: 1625. Episodes: 13.

## Probe A: Supervised Context Signal

Status: `PROMISING`. Reason: context-aware model improves held-out R2 with a positive lower CI.

| metric | n | mean | ci95 low | ci95 high |
| --- | ---: | ---: | ---: | ---: |
| r2_action_only | 25 | -0.336511 | -0.452541 | -0.231989 |
| r2_context_action | 25 | 0.716253 | 0.670693 | 0.761111 |
| r2_delta | 25 | 1.052764 | 0.956931 | 1.157185 |
| spearman_observed_action_proxy | 25 | 0.366312 | 0.314507 | 0.421031 |

Counterfactual Spearman note: the model-selected unexecuted action reward is not identifiable from this one-action-per-state log. The Spearman reported above is the held-out observed-action proxy.

## Probe B: Random-Block OPE

Status: `INCONCLUSIVE_SUPPORT`. Reason: too few exact target-policy action matches under uniform random logging; OPE is diagnostic only.
Random rows: 125. Exact target-action matches: 0. Effective sample size: 0.000.
Behavior random reward: mean `0.387900`, CI `[0.120287, 0.719673]`.
Target direct method: mean `0.515037`, CI `[0.185025, 0.936685]`.
Target IS: mean `0.000000`, CI `[0.000000, 0.000000]`.
Target doubly robust: mean `0.515037`, CI `[0.185025, 0.936685]`.

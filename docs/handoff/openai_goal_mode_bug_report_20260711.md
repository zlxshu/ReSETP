# Codex Goal Mode Ignores Low-Frequency Monitoring and Generates Repeated Empty Turns

## Summary

During a long-running local experiment, Codex Goal mode repeatedly triggered assistant turns every few seconds even after the user explicitly requested monitoring no more frequently than once every 30--60 minutes. Pausing the goal did not reliably stop already queued or subsequently reactivated continuations. Empty, HTML-comment-only, and zero-width responses still created turns and consumed tokens/credits.

## Environment

- Codex desktop app on macOS
- Local project with a long-running Python experiment and a separate local watchdog
- Goal thread ID observed during the incident: `019f4d31-bb11-7c92-b498-036871e880f6`
- Incident date: 2026-07-11 (Asia/Singapore)

## Reproduction steps

1. Start a persistent Goal-mode task that launches a multi-hour local process.
2. Ask the assistant to monitor the process only every 30--60 minutes because a local watchdog already checks health.
3. Pause Goal mode in the UI.
4. Observe that automatic goal-continuation turns continue to arrive, or that the goal returns to `active` after user interaction.
5. Have the assistant mark the goal `blocked` after the repeated-blocker threshold.
6. Observe additional goal-continuation turns after the blocked update, especially after a new user message resumes the goal.

## Expected behavior

- A paused or blocked goal should not enqueue or deliver automatic continuation turns.
- Goal mode should support a configurable minimum continuation interval for long-running jobs.
- A continuation that has no work to perform should not create a user-visible turn or consume normal model credits.
- The assistant should have a supported `pause`/`resume` control when the user explicitly delegates monitoring control.

## Actual behavior

- The system repeatedly injected goal continuations at a much higher frequency than requested.
- `get_goal` showed the goal returning to `active` after the user had paused it.
- The assistant-facing goal API exposed only `complete` and `blocked`, not `pause` or `resume`.
- Marking the goal blocked stopped it only temporarily; a subsequent user message resumed the loop.
- Empty or invisible responses still counted as turns and consumed tokens/credits.
- An attempt to use the Computer Use runtime to pause the goal through the UI failed with `Sky Computer Use native pipe startup failed`.

## User impact

- Large and unnecessary token/credit consumption during a task whose computation was entirely local.
- Message spam while the user was trying to sleep.
- The assistant spent effort managing Goal mode instead of scientific work.
- The user lost confidence in Goal mode for long-running experiments.

## Suggested fixes

1. Add assistant-callable `pause_goal` and `resume_goal` operations with explicit user authorization.
2. Add a per-goal minimum continuation interval and a first-class long-running-job mode (for example, 30 or 60 minutes).
3. Cancel all queued continuations when a goal is paused or blocked.
4. Do not create a visible/credit-bearing turn when a continuation produces no work or no notification.
5. Keep heartbeat/automation scheduling independent from Goal activation so user messages do not silently reactivate rapid polling.
6. Surface the next scheduled continuation time and pending continuation count in the UI.

## Workaround used

Goal mode was disabled and replaced with a separate hourly heartbeat that inspected the local watchdog once. Normal checks used `DONT_NOTIFY`; only completion, failure, or a material decision generated a notification.

This file is a draft only. Do not submit it to OpenAI without the user's action-time confirmation.

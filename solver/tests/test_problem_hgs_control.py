from setp_hgs_kernel.HGSControl import HGSControl


def test_shared_hgs_control_preserves_copied_restart_semantics() -> None:
    best = [10]
    restarts: list[int] = []

    control = HGSControl(
        should_stop=lambda state: state.iterations >= 4,
        best_value=lambda: best[0],
        restart_after_iterations_without_improvement=2,
        restart=lambda: restarts.append(control.state.iterations),
        initial_iterations_without_improvement=1,
    )
    for iteration in control.iterations():
        if iteration.iteration == 0:
            best[0] = 9

    assert control.state.iterations == 4
    assert restarts == [2, 3]


def test_full_problem_adapter_can_report_complete_evaluation_improvement() -> None:
    best = [10]
    seen_without_improvement: list[int] = []

    def should_stop(state) -> bool:
        seen_without_improvement.append(
            state.iterations_without_improvement
        )
        return state.iterations >= 3

    control = HGSControl(
        should_stop=should_stop,
        best_value=lambda: best[0],
        restart_after_iterations_without_improvement=None,
        initial_iterations_without_improvement=0,
    )
    for iteration in control.iterations():
        iteration.improved = iteration.iteration == 1

    assert seen_without_improvement == [0, 1, 0, 1]

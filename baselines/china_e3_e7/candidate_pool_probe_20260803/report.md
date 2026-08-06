# SEEDPROBE3 候选池测量记录

## 测量范围

固定算例 `cn-cy-100c-01-V2-LOCATIONS`、level=25，运行 100×seed1、100×seed2、25000×seed1 三个单元。每个单元沿 `fleet_worker → run_unit → _run_arm → run_hgs_route_pool_recombination → _run_exact_epoch` 路径运行；下表每行对应一个单元与一个视角。

## 单元开始前的启动记录

首次父进程使用 `/opt/anaconda3/bin/python3.13` 启动，在任何单元开始前因 `ModuleNotFoundError: No module named 'pyvrp'` 退出；当时完成单元数为 0，没有生成 `raw_pool.csv`。随后使用系统 Python 3.13，并从仓库冻结的 `build/python_envs/pyvrp-hgs-0.12.2` 补充 PyVRP 0.12.2 包路径。

## 配置链五问

### Q1

fleet 路径的 scout 配置改写实例与迭代量，没有改写归档候选常量；_run_arm 将值为 24 的 ARCHIVE_CANDIDATES_PER_VIEW 显式传给 max_archive_candidates_per_view，没有采用 route_pool_sp 的形参默认值。

`baselines/china_e3_e7/scout_three_mechanisms_20260803_runner.py:447-482`

```python
def _configure_fleet() -> Any:
    import baselines.china_e3_e7.run_formal_fleet_levels_xb_20260802 as old

    old.INSTANCE_ID = INSTANCE_ID
    old.MAX_ITERATIONS = ITERATIONS_PER_VIEW
    old.MAX_NO_IMPROVEMENT = ITERATIONS_PER_VIEW
    original_authority_rows = old.authority_rows
    original_allocations = old.allocations_by_level
    old.authority_rows = lambda instance_id=INSTANCE_ID: original_authority_rows(instance_id)
    old.allocations_by_level = lambda instance_id=INSTANCE_ID: original_allocations(instance_id)

    class IterationOnlyPatch:
        def __init__(self, ignored: int) -> None:
            self.original_builder: Any = None

        def __enter__(self) -> "IterationOnlyPatch":
            self.original_builder = old.route_pool_sp.build_pyvrp_problem

            def builder(bundle: Any, *, route_proxy_mode: str = "mechanism_ev", hard_home_depot_lock: bool = False) -> Any:
                return old.pyvrp_adapter.build_pyvrp_problem(
                    old._proxy_only_positive_type_caps(bundle),
                    route_proxy_mode=route_proxy_mode,
                    hard_home_depot_lock=hard_home_depot_lock,
                )

            old.route_pool_sp.build_pyvrp_problem = builder
            return self

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            old.route_pool_sp.build_pyvrp_problem = self.original_builder

    old._HgsContractPatch = IterationOnlyPatch
    old.infer_stop_reason = lambda observed, maximum, ignored: (
        "MAX_ITERATIONS" if int(observed) == int(maximum) else "UNEXPECTED_EARLY_STOP"
    )
    return old
```

`baselines/china_e3_e7/run_formal_fleet_levels_xb_20260802.py:76`

```python
ARCHIVE_CANDIDATES_PER_VIEW = 24
```

`baselines/china_e3_e7/run_formal_fleet_levels_xb_20260802.py:536`

```python
            max_archive_candidates_per_view=ARCHIVE_CANDIDATES_PER_VIEW,
```

### Q2

实参是整数 24，不是 Mapping；归一化进入 else 分支，为 cv_only、naive_ev、mechanism_ev 各生成 24，随后每个视角把 archive_limits[mode] 作为 max_archive_candidates 传入。

`baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/route_pool_sp.py:117-130`

```python
    if isinstance(max_archive_candidates_per_view, Mapping):
        if set(max_archive_candidates_per_view) != set(modes):
            raise ValueError(
                "archive-candidate mapping must cover exactly the three "
                "registered views"
            )
        archive_limits = {
            mode: int(max_archive_candidates_per_view[mode])
            for mode in modes
        }
    else:
        archive_limits = {
            mode: int(max_archive_candidates_per_view)
            for mode in modes
```

`baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/route_pool_sp.py:208`

```python
            max_archive_candidates=archive_limits[mode],
```

### Q3

_run_arm 显式传入值为 8 的 EXACT_ELITES_PER_VIEW；route_pool_sp 转为 int 后以 exact_elite_count=8 传入每个视角。

`baselines/china_e3_e7/run_formal_fleet_levels_xb_20260802.py:75`

```python
EXACT_ELITES_PER_VIEW = 8
```

`baselines/china_e3_e7/run_formal_fleet_levels_xb_20260802.py:535`

```python
            exact_elites_per_view=EXACT_ELITES_PER_VIEW,
```

`baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/route_pool_sp.py:207`

```python
            exact_elite_count=int(exact_elites_per_view),
```

### Q4

函数体内该形参在候选选择上用于 _quality_diverse_native_archive 的 limit，或用于普通分支排序后的切片；本路径未启用历史种群归档，走普通分支。切片发生在补全循环前，循环只遍历切片后的 proxy_ranked，因此它限制补全尝试数；另有一处把该值写入 stats。

`baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/epochal_hgs.py:172`

```python
    max_archive_candidates: int,
```

`baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/epochal_hgs.py:177`

```python
    collect_historical_population_archive: bool = False,
```

`baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/epochal_hgs.py:430-443`

```python
    if collect_historical_population_archive:
        proxy_ranked, quality_archive_count = (
            _quality_diverse_native_archive(
                tuple(unique.values()),
                cost_evaluator,
                limit=int(max_archive_candidates),
            )
        )
    else:
        proxy_ranked = sorted(
            unique.values(),
            key=cost_evaluator.cost,
        )[: int(max_archive_candidates)]
        quality_archive_count = len(proxy_ranked)
```

`baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/epochal_hgs.py:475-476`

```python
    for native in proxy_ranked:
        archive_completion_attempts += 1
```

`baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/epochal_hgs.py:715`

```python
            "archive_candidate_limit": int(max_archive_candidates),
```

### Q5

从 PyVRP 运行结果和种群组装到两个输出集合的连续主体为 epochal_hgs.py:411-825。丢弃点包括：427-429 按 native key 去重；430-443 按上限截断；499-512 在硬 home-depot 锁开启且出现跨场服务时过滤；532-543 捕获 IndexError、KeyError、TypeError、ValueError 后不加入 exact_candidates；594 对 elite_completions 按 exact_elite_count 截断。421-443 没有单独的 is_feasible() 丢弃语句；本路径 hard_home_depot_lock=False、exact_checkpoint_interval_iterations=None。archive_completions 使用完整的 exact_ranked，未在 819-821 再截断。

`baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/epochal_hgs.py:411-443`

```python
    result = algorithm.run(
        stop,
        collect_stats=True,
        display=False,
        display_interval=params.display_interval,
    )
    cost_evaluator = penalty_manager.cost_evaluator()
    historical_population_items = list(
        getattr(algorithm, "historical_population", ())
    )
    population_items = [
        *initial_solutions,
        *list(population),
        *historical_population_items,
    ]
    population_items.append(result.best)
    unique: dict[tuple[Any, ...], Any] = {}
    for native in population_items:
        unique.setdefault(_native_solution_key(native), native)
    if collect_historical_population_archive:
        proxy_ranked, quality_archive_count = (
            _quality_diverse_native_archive(
                tuple(unique.values()),
                cost_evaluator,
                limit=int(max_archive_candidates),
            )
        )
    else:
        proxy_ranked = sorted(
            unique.values(),
            key=cost_evaluator.cost,
        )[: int(max_archive_candidates)]
        quality_archive_count = len(proxy_ranked)
```

`baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/epochal_hgs.py:475-543`

```python
    for native in proxy_ranked:
        archive_completion_attempts += 1
        try:
            skeleton = _translate_solution(native, problem)
            annotated_skeleton = annotate_cross_site_services(
                skeleton,
                bundle.customer_home_depot,
            )
            if annotated_skeleton.cross_site_services:
                cross_depot_candidate_attempts += 1
                for service in annotated_skeleton.cross_site_services:
                    owner = bundle.customer_home_depot[
                        service.customer_id
                    ]
                    direction = (
                        f"{owner}->{service.served_by_depot_id}"
                    )
                    cross_depot_direction_counts[direction] = (
                        cross_depot_direction_counts.get(direction, 0) + 1
                    )
            completion = complete_china81_route_skeleton(
                skeleton,
                bundle,
            )
            if (
                problem.hard_home_depot_lock
                and completion.solution.cross_site_services
            ):
                hard_lock_filtered_archive_candidates += 1
                complete_candidate_evaluation_trace.append(
                    {
                        "source": "terminal_population_archive",
                        "iteration": None,
                        "complete_objective": None,
                        "status": "FILTERED_HARD_HOME_DEPOT_LOCK",
                    }
                )
                continue
            if completion.solution.cross_site_services:
                cross_depot_completed_candidates += 1
            exact_candidates.append(
                (
                    skeleton,
                    completion,
                    int(cost_evaluator.cost(native)),
                )
            )
            complete_candidate_evaluation_trace.append(
                {
                    "source": "terminal_population_archive",
                    "iteration": None,
                    "complete_objective": float(
                        completion.objective
                    ),
                    "status": "PASS",
                }
            )
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            failures.append(str(exc))
            complete_candidate_evaluation_trace.append(
                {
                    "source": "terminal_population_archive",
                    "iteration": None,
                    "complete_objective": None,
                    "status": "INFEASIBLE_OR_ERROR",
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                }
            )
```

`baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/epochal_hgs.py:544-594`

```python
    base_exact_candidates = list(exact_candidates)
    exact_candidates.extend(checkpoint_candidates)
    common_completion = complete_china81_route_skeleton(
        common_initial_solution,
        bundle,
    )
    complete_candidate_evaluation_trace.append(
        {
            "source": "common_initial_solution",
            "iteration": None,
            "complete_objective": float(common_completion.objective),
            "status": "PASS",
        }
    )
    if (
        problem.hard_home_depot_lock
        and common_completion.solution.cross_site_services
    ):
        raise ValueError(
            "hard home-depot control initial solution contains "
            "cross-site service"
        )
    exact_candidates.append(
        (
            common_initial_solution,
            common_completion,
            -1,
        )
    )
    base_exact_candidates.append(
        (
            common_initial_solution,
            common_completion,
            -1,
        )
    )
    base_exact_ranked = sorted(
        base_exact_candidates,
        key=lambda item: (
            item[1].objective,
            item[2],
        ),
    )
    exact_ranked = sorted(
        exact_candidates,
        key=lambda item: (
            item[1].objective,
            item[2],
        ),
    )
    selected = exact_ranked[: int(exact_elite_count)]
```

`baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/epochal_hgs.py:664-667`

```python
    return HgsExactEpoch(
        elite_skeletons=tuple(item[0] for item in selected),
        elite_completions=tuple(item[1] for item in selected),
        proxy_best_completion=proxy_best_completion,
```

`baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/epochal_hgs.py:819-824`

```python
        archive_completions=tuple(
            item[1] for item in exact_ranked
        ),
        base_archive_completions=tuple(
            item[1] for item in base_exact_ranked
        ),
```

`baselines/china_e3_e7/run_formal_fleet_levels_xb_20260802.py:538`

```python
            hard_home_depot_lock=False,
```

`baselines/china_e3_e7/run_formal_fleet_levels_xb_20260802.py:541`

```python
            exact_checkpoint_interval_iterations=None,
```

### Q5 连续代码段

`baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/epochal_hgs.py:411-825`

```text
411      result = algorithm.run(
412          stop,
413          collect_stats=True,
414          display=False,
415          display_interval=params.display_interval,
416      )
417      cost_evaluator = penalty_manager.cost_evaluator()
418      historical_population_items = list(
419          getattr(algorithm, "historical_population", ())
420      )
421      population_items = [
422          *initial_solutions,
423          *list(population),
424          *historical_population_items,
425      ]
426      population_items.append(result.best)
427      unique: dict[tuple[Any, ...], Any] = {}
428      for native in population_items:
429          unique.setdefault(_native_solution_key(native), native)
430      if collect_historical_population_archive:
431          proxy_ranked, quality_archive_count = (
432              _quality_diverse_native_archive(
433                  tuple(unique.values()),
434                  cost_evaluator,
435                  limit=int(max_archive_candidates),
436              )
437          )
438      else:
439          proxy_ranked = sorted(
440              unique.values(),
441              key=cost_evaluator.cost,
442          )[: int(max_archive_candidates)]
443          quality_archive_count = len(proxy_ranked)
444      diversity_archive_count = (
445          len(proxy_ranked) - quality_archive_count
446      )
447      exact_candidates: list[
448          tuple[Solution, China81CompletionResult, int]
449      ] = []
450      complete_candidate_evaluation_trace: list[dict[str, Any]] = [
451          {
452              "source": "hgs_iteration_checkpoint",
453              "iteration": int(observation["iteration"]),
454              "complete_objective": observation["complete_objective"],
455              "status": observation["status"],
456              **(
457                  {
458                      "exception_type": observation["exception_type"],
459                      "exception_message": observation[
460                          "exception_message"
461                      ],
462                  }
463                  if "exception_type" in observation
464                  else {}
465              ),
466          }
467          for observation in checkpoint_observations
468      ]
469      failures: list[str] = []
470      archive_completion_attempts = 0
471      hard_lock_filtered_archive_candidates = 0
472      cross_depot_candidate_attempts = 0
473      cross_depot_completed_candidates = 0
474      cross_depot_direction_counts: dict[str, int] = {}
475      for native in proxy_ranked:
476          archive_completion_attempts += 1
477          try:
478              skeleton = _translate_solution(native, problem)
479              annotated_skeleton = annotate_cross_site_services(
480                  skeleton,
481                  bundle.customer_home_depot,
482              )
483              if annotated_skeleton.cross_site_services:
484                  cross_depot_candidate_attempts += 1
485                  for service in annotated_skeleton.cross_site_services:
486                      owner = bundle.customer_home_depot[
487                          service.customer_id
488                      ]
489                      direction = (
490                          f"{owner}->{service.served_by_depot_id}"
491                      )
492                      cross_depot_direction_counts[direction] = (
493                          cross_depot_direction_counts.get(direction, 0) + 1
494                      )
495              completion = complete_china81_route_skeleton(
496                  skeleton,
497                  bundle,
498              )
499              if (
500                  problem.hard_home_depot_lock
501                  and completion.solution.cross_site_services
502              ):
503                  hard_lock_filtered_archive_candidates += 1
504                  complete_candidate_evaluation_trace.append(
505                      {
506                          "source": "terminal_population_archive",
507                          "iteration": None,
508                          "complete_objective": None,
509                          "status": "FILTERED_HARD_HOME_DEPOT_LOCK",
510                      }
511                  )
512                  continue
513              if completion.solution.cross_site_services:
514                  cross_depot_completed_candidates += 1
515              exact_candidates.append(
516                  (
517                      skeleton,
518                      completion,
519                      int(cost_evaluator.cost(native)),
520                  )
521              )
522              complete_candidate_evaluation_trace.append(
523                  {
524                      "source": "terminal_population_archive",
525                      "iteration": None,
526                      "complete_objective": float(
527                          completion.objective
528                      ),
529                      "status": "PASS",
530                  }
531              )
532          except (IndexError, KeyError, TypeError, ValueError) as exc:
533              failures.append(str(exc))
534              complete_candidate_evaluation_trace.append(
535                  {
536                      "source": "terminal_population_archive",
537                      "iteration": None,
538                      "complete_objective": None,
539                      "status": "INFEASIBLE_OR_ERROR",
540                      "exception_type": type(exc).__name__,
541                      "exception_message": str(exc),
542                  }
543              )
544      base_exact_candidates = list(exact_candidates)
545      exact_candidates.extend(checkpoint_candidates)
546      common_completion = complete_china81_route_skeleton(
547          common_initial_solution,
548          bundle,
549      )
550      complete_candidate_evaluation_trace.append(
551          {
552              "source": "common_initial_solution",
553              "iteration": None,
554              "complete_objective": float(common_completion.objective),
555              "status": "PASS",
556          }
557      )
558      if (
559          problem.hard_home_depot_lock
560          and common_completion.solution.cross_site_services
561      ):
562          raise ValueError(
563              "hard home-depot control initial solution contains "
564              "cross-site service"
565          )
566      exact_candidates.append(
567          (
568              common_initial_solution,
569              common_completion,
570              -1,
571          )
572      )
573      base_exact_candidates.append(
574          (
575              common_initial_solution,
576              common_completion,
577              -1,
578          )
579      )
580      base_exact_ranked = sorted(
581          base_exact_candidates,
582          key=lambda item: (
583              item[1].objective,
584              item[2],
585          ),
586      )
587      exact_ranked = sorted(
588          exact_candidates,
589          key=lambda item: (
590              item[1].objective,
591              item[2],
592          ),
593      )
594      selected = exact_ranked[: int(exact_elite_count)]
595      proxy_best_completion_failure: str | None = None
596      proxy_best_completion_attempts = 1
597      hard_lock_filtered_proxy_best_candidates = 0
598      try:
599          proxy_best_completion = complete_china81_route_skeleton(
600              _translate_solution(result.best, problem),
601              bundle,
602          )
603          if (
604              problem.hard_home_depot_lock
605              and proxy_best_completion.solution.cross_site_services
606          ):
607              hard_lock_filtered_proxy_best_candidates = 1
608              proxy_best_completion_failure = (
609                  "FILTERED_HARD_HOME_DEPOT_LOCK"
610              )
611              complete_candidate_evaluation_trace.append(
612                  {
613                      "source": "proxy_best_solution",
614                      "iteration": int(result.num_iterations),
615                      "complete_objective": None,
616                      "status": "FILTERED_HARD_HOME_DEPOT_LOCK",
617                  }
618              )
619              proxy_best_completion = min(
620                  (item[1] for item in exact_candidates),
621                  key=lambda item: item.objective,
622              )
623          else:
624              complete_candidate_evaluation_trace.append(
625                  {
626                      "source": "proxy_best_solution",
627                      "iteration": int(result.num_iterations),
628                      "complete_objective": float(
629                          proxy_best_completion.objective
630                      ),
631                      "status": "PASS",
632                  }
633              )
634      except (IndexError, KeyError, TypeError, ValueError) as exc:
635          proxy_best_completion_failure = str(exc)
636          complete_candidate_evaluation_trace.append(
637              {
638                  "source": "proxy_best_solution",
639                  "iteration": int(result.num_iterations),
640                  "complete_objective": None,
641                  "status": "INFEASIBLE_OR_ERROR",
642                  "exception_type": type(exc).__name__,
643                  "exception_message": str(exc),
644              }
645          )
646          proxy_best_completion = min(
647              (item[1] for item in exact_candidates),
648              key=lambda item: item.objective,
649          )
650      complete_candidate_evaluation_attempts = (
651          archive_completion_attempts
652          + len(checkpoint_observations)
653          + 1
654          + proxy_best_completion_attempts
655      )
656      if (
657          len(complete_candidate_evaluation_trace)
658          != complete_candidate_evaluation_attempts
659      ):
660          raise RuntimeError(
661              "complete-candidate trace does not match the frozen "
662              "evaluation-attempt counter"
663          )
664      return HgsExactEpoch(
665          elite_skeletons=tuple(item[0] for item in selected),
666          elite_completions=tuple(item[1] for item in selected),
667          proxy_best_completion=proxy_best_completion,
668          elapsed_seconds=perf_counter() - started,
669          stats={
670              "seed": int(seed),
671              "runtime_seconds": (
672                  None
673                  if runtime_seconds is None
674                  else float(runtime_seconds)
675              ),
676              "hgs_stop_mode": stop_mode,
677              "max_hgs_iterations": (
678                  None
679                  if max_hgs_iterations is None
680                  else int(max_hgs_iterations)
681              ),
682              "max_no_improvement_iterations": (
683                  None
684                  if max_no_improvement_iterations is None
685                  else int(max_no_improvement_iterations)
686              ),
687              "wallclock_safety_seconds": (
688                  None
689                  if wallclock_safety_seconds is None
690                  else float(wallclock_safety_seconds)
691              ),
692              "wallclock_safety_triggered": bool(
693                  safety is not None and safety.triggered
694              ),
695              "warm_elite_count": len(warm_native),
696              "warm_input_route_type_counts": (
697                  warm_input_route_type_counts
698              ),
699              "warm_projected_route_type_counts": (
700                  warm_projected_route_type_counts
701              ),
702              "warm_route_type_preserved": (
703                  warm_route_type_preserved
704              ),
705              "population_size": len(population),
706              "unique_feasible_population_size": sum(
707                  item.is_feasible()
708                  for item in unique.values()
709              ),
710              "unique_proxy_population_size": len(unique),
711              "proxy_feasible_population_size": sum(
712                  item.is_feasible()
713                  for item in unique.values()
714              ),
715              "archive_candidate_limit": int(max_archive_candidates),
716              "historical_population_archive_enabled": bool(
717                  collect_historical_population_archive
718              ),
719              "historical_population_snapshot_count": int(
720                  getattr(algorithm, "population_snapshot_count", 0)
721              ),
722              "historical_population_candidate_references": len(
723                  historical_population_items
724              ),
725              "archive_unique_native_candidates": len(unique),
726              "archive_quality_selected_count": (
727                  quality_archive_count
728              ),
729              "archive_diversity_selected_count": (
730                  diversity_archive_count
731              ),
732              "archive_completion_attempts": (
733                  archive_completion_attempts
734              ),
735              "archive_candidates_screened": (
736                  archive_completion_attempts
737              ),
738              "hard_lock_filtered_archive_candidates": (
739                  hard_lock_filtered_archive_candidates
740              ),
741              "archive_candidates_completed": (
742                  len(exact_candidates) - 1
743              ),
744              "archive_completion_failures": failures,
745              "exact_checkpoint_interval_iterations": (
746                  exact_checkpoint_interval_iterations
747              ),
748              "exact_checkpoint_attempts": len(
749                  checkpoint_observations
750              ),
751              "exact_checkpoint_candidates_screened": (
752                  len(checkpoint_observations)
753              ),
754              "hard_lock_filtered_checkpoint_candidates": (
755                  hard_lock_filtered_checkpoint_candidates
756              ),
757              "exact_checkpoint_completed": len(
758                  checkpoint_candidates
759              ),
760              "exact_checkpoint_failures": checkpoint_failures,
761              "exact_checkpoint_observations": (
762                  checkpoint_observations
763              ),
764              "common_initial_completion_attempts": 1,
765              "proxy_best_completion_attempts": (
766                  proxy_best_completion_attempts
767              ),
768              "hard_lock_filtered_proxy_best_candidates": (
769                  hard_lock_filtered_proxy_best_candidates
770              ),
771              "hard_lock_filtered_candidates": (
772                  hard_lock_filtered_archive_candidates
773                  + hard_lock_filtered_checkpoint_candidates
774                  + hard_lock_filtered_proxy_best_candidates
775              ),
776              "proxy_best_completion_failure": (
777                  proxy_best_completion_failure
778              ),
779              "complete_candidate_evaluation_attempts": (
780                  complete_candidate_evaluation_attempts
781              ),
782              "complete_candidate_evaluation_trace": (
783                  complete_candidate_evaluation_trace
784              ),
785              "hgs_iterations": int(result.num_iterations),
786              "active_node_operators": active_node_operators,
787              "active_route_operators": active_route_operators,
788              "hard_home_depot_lock": bool(
789                  problem.hard_home_depot_lock
790              ),
791              "reciprocal_cross_depot_operator": (
792                  "Exchange11"
793                  if (
794                      not problem.hard_home_depot_lock
795                      and "Exchange11" in active_node_operators
796                  )
797                  else None
798              ),
799              "reciprocal_cross_depot_neighbourhood_enabled": bool(
800                  not problem.hard_home_depot_lock
801                  and "Exchange11" in active_node_operators
802              ),
803              "cross_depot_candidate_attempts": (
804                  cross_depot_candidate_attempts
805              ),
806              "cross_depot_completed_candidates": (
807                  cross_depot_completed_candidates
808              ),
809              "cross_depot_direction_counts": (
810                  cross_depot_direction_counts
811              ),
812              "proxy_best_exact_objective": float(
813                  proxy_best_completion.objective
814              ),
815              "selected_exact_objectives": [
816                  float(item[1].objective) for item in selected
817              ],
818          },
819          archive_completions=tuple(
820              item[1] for item in exact_ranked
821          ),
822          base_archive_completions=tuple(
823              item[1] for item in base_exact_ranked
824          ),
825      )
```

## 9 行实测数据

| 迭代 | 种子 | 视角 | 状态 | 截断前候选 | 生效上限 | 发起补全 | 补全成功 | 补全失败 | 失败原文计数 | archive 数 | elite 数 | 成功目标不同值数 | 成功目标值 hex |
|---:|---:|---|---|---:|---:|---:|---:|---:|---|---:|---:|---:|---|
| 100 | 1 | cv_only | PASS | 111 | 24 | 24 | 0 | 24 | {"ValueError: China81 route skeleton cannot satisfy the registered physical fleet caps at 'D_chengdu': overage=(2, 0, 2)":2,"ValueError: China81 route skeleton cannot satisfy the registered physical fleet caps at 'D_chengdu': overage=(3, 0, 3)":5,"ValueError: China81 route skeleton cannot satisfy the registered physical fleet caps at 'D_chengdu': overage=(4, 0, 4)":16,"ValueError: China81 route skeleton cannot satisfy the registered physical fleet caps at 'D_chengdu': overage=(5, 0, 5)":1} | 1 | 1 | 0 | [] |
| 100 | 1 | naive_ev | PASS | 118 | 24 | 24 | 0 | 24 | {"ValueError: China81 route skeleton cannot satisfy the registered physical fleet caps at 'D_chengdu': overage=(1, 0, 1)":23,"ValueError: China81 route skeleton cannot satisfy the registered physical fleet caps at 'D_chongqing': overage=(1, 0, 1)":1} | 1 | 1 | 0 | [] |
| 100 | 1 | mechanism_ev | PASS | 102 | 24 | 24 | 0 | 24 | {"ValueError: China81 route skeleton cannot satisfy the registered physical fleet caps at 'D_chengdu': overage=(1, 0, 1)":7,"ValueError: China81 route skeleton cannot satisfy the registered physical fleet caps at 'D_chengdu': overage=(2, 0, 2)":16,"ValueError: E3_STRICT_MULTITRIP_V2: route CH81-0018 misses C055's time window":1} | 1 | 1 | 0 | [] |
| 100 | 2 | cv_only | PASS | 123 | 24 | 24 | 0 | 24 | {"ValueError: China81 route skeleton cannot satisfy the registered physical fleet caps at 'D_chengdu': overage=(2, 0, 2)":6,"ValueError: China81 route skeleton cannot satisfy the registered physical fleet caps at 'D_chengdu': overage=(3, 0, 3)":11,"ValueError: China81 route skeleton cannot satisfy the registered physical fleet caps at 'D_chengdu': overage=(4, 0, 4)":7} | 1 | 1 | 0 | [] |
| 100 | 2 | naive_ev | PASS | 101 | 24 | 24 | 0 | 24 | {"ValueError: China81 route skeleton cannot satisfy the registered physical fleet caps at 'D_chengdu': overage=(1, 0, 1)":3,"ValueError: China81 route skeleton cannot satisfy the registered physical fleet caps at 'D_chengdu': overage=(2, 0, 2)":21} | 1 | 1 | 0 | [] |
| 100 | 2 | mechanism_ev | PASS | 110 | 24 | 24 | 0 | 24 | {"ValueError: China81 route skeleton cannot satisfy the registered physical fleet caps at 'D_chengdu': overage=(1, 0, 1)":4,"ValueError: China81 route skeleton cannot satisfy the registered physical fleet caps at 'D_chengdu': overage=(2, 0, 2)":20} | 1 | 1 | 0 | [] |
| 25000 | 1 | cv_only | PASS | 86 | 24 | 24 | 0 | 24 | {"ValueError: China81 route skeleton cannot satisfy the registered physical fleet caps at 'D_chengdu': overage=(1, 0, 1)":24} | 1 | 1 | 0 | [] |
| 25000 | 1 | naive_ev | PASS | 107 | 24 | 24 | 0 | 24 | {"ValueError: China81 route skeleton cannot satisfy the registered physical fleet caps at 'D_chengdu': overage=(1, 0, 1)":24} | 1 | 1 | 0 | [] |
| 25000 | 1 | mechanism_ev | PASS | 92 | 24 | 24 | 0 | 24 | {"ValueError: China81 route skeleton cannot satisfy the registered physical fleet caps at 'D_chengdu': overage=(1, 0, 1)":24} | 1 | 1 | 0 | [] |

## 各量取得方式

`proxy_ranked_count`：打补丁保留返回对象后直接读；HgsExactEpoch.stats.archive_unique_native_candidates；即 unique 代理候选在上限切片前的数量。

`max_archive_candidates_effective`：打补丁保留返回对象后直接读；HgsExactEpoch.stats.archive_candidate_limit。

`completion_attempted`：打补丁保留返回对象后直接读；HgsExactEpoch.stats.archive_completion_attempts。

`completion_succeeded`：打补丁保留返回对象后直接读；complete_candidate_evaluation_trace 中 source=terminal_population_archive 且 status=PASS 的条数。

`completion_failed`：打补丁保留返回对象后直接读；同一 trace 中 source=terminal_population_archive 且 status 不是 PASS 的条数。

`completion_failure_reasons`：打补丁保留返回对象后直接读；逐条保留 trace 的 exception_type 与 exception_message 前 200 字符并计数；无异常字段时保留原 status。

`archive_completions_count`：打补丁保留返回对象后直接读；len(HgsExactEpoch.archive_completions)。

`elite_completions_count`：打补丁保留返回对象后直接读；len(HgsExactEpoch.elite_completions)。

`distinct_full_objective_among_succeeded`：打补丁保留返回对象后直接读再计算；terminal_population_archive 的 PASS 完整目标值转 float.hex 后去重计数。

`succeeded_full_objectives_float_hex`：打补丁保留返回对象后直接读；completion_succeeded 大于 1 时按补全 trace 顺序列出全部完整目标值的 float.hex。

## 取不到的量

无。

## 单元异常原文

无。

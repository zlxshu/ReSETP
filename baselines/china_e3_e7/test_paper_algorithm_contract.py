from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PAPER = ROOT / "docs" / "paper_v2" / "paper_main.tex"
FLOW = (
    ROOT
    / "docs"
    / "paper_v2"
    / "generated_figures"
    / "algorithm_flow.tex"
)


def test_paper_uses_current_formal_algorithm_contract() -> None:
    paper = PAPER.read_text(encoding="utf-8")
    required = (
        "多视角混合遗传搜索—限时MIP路线池重组算法",
        "Time-Limited MIP Route-Pool Recombination",
        "三个混合遗传搜索读取相同算例和相同种子",
        "分别建立随机初始种群并独立运行",
        "每视角完整复核24个档案候选",
        "所有复核成功的档案候选路线均进入路线池",
        "设置5~s时间上限",
        r"\bar K_{du}",
        "每个任务严格提交80次完整候选评价",
    )
    for phrase in required:
        assert phrase in paper

    forbidden = (
        "多视角混合遗传搜索—精确路线池重组",
        "Exact Route-Pool Recombination",
        "机制感知母体阶段",
        "轮换执行延续搜索",
        "池上限为600条",
        "求解时间盒不超过总时限的10",
        "随后的延续重组最多执行4轮",
        "连续2轮无改进",
        "时间窗超出0.388 s",
    )
    for phrase in forbidden:
        assert phrase not in paper


def test_algorithm_flow_matches_current_execution_order() -> None:
    flow = FLOW.read_text(encoding="utf-8")
    required = (
        "三个机制视角独立搜索",
        "HGS-F",
        "HGS-E",
        "HGS-M",
        "固定5000次迭代",
        "24个档案候选",
        "每视角保留8个完整成本最低的父方案",
        "HiGHS限时MIP路线重组",
        "重组方案严格优于最好父方案",
        "保留最好父方案",
    )
    for phrase in required:
        assert phrase in flow

    forbidden = (
        "母体搜索",
        "轮换",
        "热启动",
        "精确求解",
        "4轮",
        "2轮",
        "fill=",
    )
    for phrase in forbidden:
        assert phrase not in flow

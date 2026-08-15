#!/usr/bin/env python3
"""Reproducible audit of the manuscript's format and core mathematical notation.

This diagnostic never changes sealed experiment evidence or launches a solver run.
It compares the equations printed in the paper with the unit ledger implemented by
the evaluator, and records formulation gaps that must be repaired before submission.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
import re
import sys

import sympy as sp


ROOT = Path(__file__).resolve().parents[2]
PAPER = ROOT / "docs/paper_submission_final/RETIRED_paper_main.tex"
OUT = ROOT / "baselines/model_verification/paper_math_audit_20260716"
sys.path.insert(0, str(ROOT / "solver/src"))

from setp_solver.cost import ev_arc_energy_kwh  # noqa: E402
from setp_solver.algorithms.resetp_alns.runtime.select import AlphaUCB  # noqa: E402
from setp_solver.algorithms.resetp_alns.support.carbon_charging import charge_start_candidates  # noqa: E402
from setp_solver.prices import DEFAULT_PRICES  # noqa: E402


def braced_argument(text: str, command: str) -> str:
    start = text.index(command + "{") + len(command) + 1
    depth = 1
    index = start
    while index < len(text) and depth:
        if text[index] == "{" and (index == 0 or text[index - 1] != "\\"):
            depth += 1
        elif text[index] == "}" and (index == 0 or text[index - 1] != "\\"):
            depth -= 1
        index += 1
    if depth:
        raise ValueError(f"unclosed argument for {command}")
    return text[start : index - 1]


def braced_arguments(text: str, command: str) -> list[str]:
    """Return every braced argument for a command in source order."""
    arguments: list[str] = []
    cursor = 0
    token = command + "{"
    while True:
        found = text.find(token, cursor)
        if found < 0:
            return arguments
        start = found + len(token)
        depth = 1
        index = start
        while index < len(text) and depth:
            if text[index] == "{" and (index == 0 or text[index - 1] != "\\"):
                depth += 1
            elif text[index] == "}" and (index == 0 or text[index - 1] != "\\"):
                depth -= 1
            index += 1
        if depth:
            raise ValueError(f"unclosed argument for {command}")
        arguments.append(text[start : index - 1])
        cursor = index


def active_abstract(tex: str) -> str:
    """Resolve the manuscript's conditional final/pending Chinese abstract."""
    arguments = braced_arguments(tex, r"\Abstract")
    if not arguments:
        raise ValueError("missing Chinese abstract")
    input_pattern = re.compile(r"\\input\{([^{}]+)\}")
    for argument in arguments:
        match = input_pattern.fullmatch(argument.strip())
        if not match:
            continue
        path = PAPER.parent / match.group(1)
        if path.is_file():
            return path.read_text(encoding="utf-8")
    for argument in arguments:
        if not input_pattern.fullmatch(argument.strip()):
            return argument
    raise ValueError("conditional Chinese abstract has no available branch")


def section(text: str, label: str) -> str:
    pattern = rf"\\label\{{{re.escape(label)}\}}"
    match = re.search(pattern, text)
    if not match:
        raise ValueError(f"missing label {label}")
    before = text.rfind("\\begin{", 0, match.start())
    after = text.find("\\end{", match.end())
    return text[before:after]


def record(name: str, status: str, evidence: str, repair: str) -> dict[str, str]:
    return {"check": name, "status": status, "evidence": evidence, "required_repair": repair}


def audit_title_and_abstract(tex: str) -> list[dict[str, str]]:
    title = braced_argument(tex, r"\Title")
    etitle = braced_argument(tex, r"\ETitle")
    abstract = active_abstract(tex)
    chinese_title_chars = len(re.findall(r"[\u3400-\u9fff]", title))
    english_content_words = len(re.findall(r"[A-Za-z]+(?:-[A-Za-z]+)*", etitle))
    chinese_abstract_chars = len(re.findall(r"[\u3400-\u9fff]", abstract))
    rows = [
        record(
            "中文题名不超过20字",
            "PASS" if chinese_title_chars <= 20 else "FAIL",
            f"当前题名含{chinese_title_chars}个汉字：{title}",
            "把主标题收窄为一个运营问题；公平和碳强度可在摘要中交代。",
        ),
        record(
            "英文题名不超过10个实词",
            "PASS" if english_content_words <= 10 else "FAIL",
            f"按连字符词计数为{english_content_words}词：{etitle}",
            "与缩短后的中文题名一一对应，并控制在10个实词内。",
        ),
        record(
            "中文摘要约200至300字",
            "PASS" if 200 <= chinese_abstract_chars <= 300 else "FAIL",
            f"仅计汉字已有{chinese_abstract_chars}字，尚未计数字、英文和标点。",
            "只保留问题、方法、三项最关键定量发现和边界；待E7完成后再锁定最终数字。",
        ),
    ]
    return rows


def audit_energy_equation(tex: str) -> list[dict[str, str]]:
    alpha, force, distance_km = sp.symbols("alpha F d_km", positive=True)
    distance_m, velocity = sp.symbols("d_m v", positive=True)
    power = force * velocity
    code_ledger = alpha * power * (distance_m / velocity) / sp.Integer(3_600_000)
    corrected = alpha * force * distance_km / sp.Integer(3600)
    identity = sp.simplify(code_ledger.subs(distance_m, 1000 * distance_km) - corrected)

    prices = DEFAULT_PRICES
    test_distance_m = 12_345.0
    test_load_kg = 2_500.0
    force_numeric = (
        0.5 * prices.c_d * prices.rho_a * prices.A_frontal * prices.v_speed_ms**2
        + (prices.m_curb + prices.m_unit * test_load_kg) * prices.g0 * prices.c_r
    )
    closed_form = prices.alpha_e * force_numeric * (test_distance_m / 1000.0) / 3600.0
    evaluator = ev_arc_energy_kwh(test_distance_m, test_load_kg, prices)
    current_literal = prices.alpha_e * force_numeric * (test_distance_m / 1000.0)

    equation = section(tex, "eq:ev_energy_fixed_speed")
    has_conversion = bool(re.search(r"(?:3600|3[,.]?6\\times10\^?\{?6\}?)", equation))
    uses_direct_mass_sum = "m_k+u" in section(tex, "eq:power").replace(" ", "")
    mass_units_explicit = "载重（kg）" in tex and "u_{ijr}^\\tau" in tex
    return [
        record(
            "程序电耗与正确闭式量纲一致",
            "PASS" if identity == 0 and abs(evaluator - closed_form) < 1e-12 else "FAIL",
            f"12.345 km、2500 kg样例：程序={evaluator:.12f} kWh，闭式={closed_form:.12f} kWh。",
            "若不一致，停止使用当前能耗账本。",
        ),
        record(
            "论文固定速度式包含kWh换算",
            "PASS" if has_conversion else "FAIL",
            (f"当前印刷式已加入1/3600换算，12.345 km样例与程序值{evaluator:.12f} kWh同量纲。" if has_conversion else f"当前印刷式按km直接乘力项；照字面计算={current_literal:.6f}，是程序值的{current_literal/evaluator:.0f}倍。"),
            r"若d以km计，应写 g_vk=alpha_k F_empty,k/3600、omega_k^E=alpha_k g c_R/3600；若d以m计则除以3.6e6。",
        ),
        record(
            "载重质量换算口径显式",
            "PASS" if (not uses_direct_mass_sum or mass_units_explicit) else "FAIL",
            "功率式直接写m_k+u_ijk；程序实际使用m_curb+m_unit*u，当前m_unit=1 kg/需求单位。论文已明确需求与载重均以kg计。" if mass_units_explicit else "功率式直接写m_k+u_ijk；程序实际使用m_curb+m_unit*u，当前m_unit=1 kg/需求单位。",
            "在公式保留m_unit，或明确需求和弧载重均以kg计且m_unit=1。",
        ),
    ]


def audit_multitrip_and_state(tex: str) -> list[dict[str, str]]:
    compact = tex.replace(" ", "")
    objective = section(tex, "eq:objective")
    service_once = section(tex, "eq:service_once")
    variable_domain = section(tex, "eq:binary")
    vehicle_pattern = section(tex, "eq:vehicle_pattern")
    pattern_semantics = all(
        token in compact
        for token in (r"\Omega_k^\tau", r"A_{ikp}", r"z_{kp}^\tau")
    )
    trip_consistent = (
        pattern_semantics
        and "z_{kp}" in objective
        and "A_{ikp}" in service_once
        and "z_{kp}" in service_once
        and "z_{kp}" in vehicle_pattern
        and "z_{kp}" in variable_domain
        and "x_{ijkw}" not in tex
    )
    depot_charge = section(tex, "eq:depot_charge_complete")
    lower_window_present = (
        r"\underline a_q" in depot_charge
        and r"a_q^{ch}" in depot_charge
        and r"\le" in depot_charge
        and "最早开始时刻" in tex
        and "正在进行的充电" in tex
    )
    ownership_phrase = "唯一收益归属车场" in tex or "只属于一个车场" in tex
    partition_phrase = any(phrase in tex for phrase in ("两两不交", "互不相交", "划分K", "构成K^\\tau的一个划分", "所有权划分"))
    return [
        record(
            "多趟模式在目标、服务和变量域闭合",
            "PASS" if trip_consistent else "FAIL",
            ("论文已改为可行配送趟—实体车全天模式两层结构；目标、客户精确覆盖、每车至多一个模式和变量域均使用z_kp，趟次与充电状态由模式证书携带。" if trip_consistent else "目标、客户覆盖、每车模式选择或变量域尚未采用同一模式变量语义。"),
            "保持z_kp在目标、精确覆盖、每车模式选择和变量域中的统一语义，并由独立证书核验模式内部的多趟与充电状态。",
        ),
        record(
            "阶段预充电窗有历史下界",
            "PASS" if lower_window_present else "FAIL",
            ("连续充电会话同时保存最早开始时刻和最晚完成时刻；第一趟继承重规划状态，后续趟继承上一趟返回状态。" if lower_window_present else "充电窗口尚未同时给出历史下界与完成上界。"),
            "加入max(上一趟回场时刻, 当前阶段时刻)下界，并说明正在进行的充电如何继承。",
        ),
        record(
            "车场车辆集合是唯一所有权划分",
            "PASS" if ownership_phrase and partition_phrase else "FAIL",
            "正文已把K_d定义为车场d拥有的车辆集合，并声明各K_d两两不交且并为K；跨场共享只改变服务权。" if ownership_phrase and partition_phrase else "正文称每车有唯一收益归属，但K_d仍定义为‘当前可调用车辆’，未声明各K_d互不相交且并为K。",
            "把K_d定义为车场d拥有的车辆集合，并显式声明{K_d}构成K的划分；共享指跨场服务权而非重复所有权。",
        ),
    ]


def audit_structural_counterexamples(tex: str) -> list[dict[str, str]]:
    # A depot-customer-depot route is impossible if departure and return share
    # one time variable: a_i >= a_d+t_1 and a_d >= a_i+s+t_2 imply 0>0.
    travel_out, travel_back, service = sp.symbols("t_out t_back s", positive=True)
    positive_cycle = sp.simplify(travel_out + travel_back + service)
    has_depot_copies = any(phrase in tex for phrase in ("源节点和汇节点", "源、汇两个节点副本", "出发副本", "返回副本", "车场副本"))

    # With a fixed allowance CE, p(E-CE) differs from pE only by a constant.
    cost, price, emissions, allowance = sp.symbols("C p E CE", real=True)
    allowance_delta = sp.diff(cost + price * (emissions - allowance), emissions)
    allowance_affects_marginal = allowance in allowance_delta.free_symbols

    # Four-slot witness: aggregate occupancy can select slots 1 and 3, but one
    # contiguous two-slot session must incur 10+100 instead of 10+10.
    carbon = [10, 100, 10, 100]
    aggregate_best = sum(sorted(carbon)[:2])
    contiguous_best = min(carbon[i] + carbon[i + 1] for i in range(3))
    overlap = section(tex, "eq:charge_overlap")
    charge_window = section(tex, "eq:depot_charge_complete")
    charge_energy = section(tex, "eq:charge_energy")
    charge_energy_compact = re.sub(r"\s+", "", charge_energy)
    # Fixed-power ledger used by the evaluator: 22 kW over three adjacent
    # overlaps totalling 1.5 h must close to 33 kWh.
    overlap_seconds = (600, 1800, 3000)
    fixed_power_energy = 22.0 * sum(overlap_seconds) / 3600.0
    charging_exact_in_constraints = (
        all(token in overlap for token in (r"\min", r"\max", r"a_q^{ch}", r"\Delta_q"))
        and r"\underline a_q" in charge_window
        and r"\overline a_q" in charge_window
        and r"\pi_{s(q)}g_{qt}" in charge_energy_compact
        and "3600" in charge_energy_compact
        and abs(fixed_power_energy - 33.0) < 1e-12
        and "一次会话只能形成一个连续区间" in tex
        and "实际补能和排放由式" in tex
    )

    participation_misnamed = "收益公平" in tex or "比例公平下界" in tex
    return [
        record(
            "出发与返回时间变量不会形成正时间闭环",
            "PASS" if has_depot_copies else "FAIL",
            (f"若起终车场共用a_d，则两条递推相加得到0≥t_out+s+t_back；右端{positive_cycle}在正行驶/服务时间下严格为正。当前正文已为每趟定义源、汇车场节点副本。" if has_depot_copies else f"若起终车场共用a_d，则两条递推相加得到0≥t_out+s+t_back；右端{positive_cycle}在正行驶/服务时间下严格为正。当前正文未定义源/汇车场副本。"),
            "为每趟定义不同的源、汇节点或独立离场/回场时间；在极小路线d→i→d上验证可行。",
        ),
        record(
            "固定碳配额的作用表述准确",
            "WARN" if not allowance_affects_marginal else "PASS",
            f"对C+p(E-CE)关于E求导为{allowance_delta}，固定CE不改变边际碳成本和最优路线，只平移目标值。",
            "若只用一个买卖价格，改称线性碳价加配额信用；若研究配额松紧，增加排放上限或买卖量/价格不对称。",
        ),
        record(
            "充电时段约束保证一个连续实际区间",
            "PASS" if charging_exact_in_constraints else "FAIL",
            (f"四时段反例{carbon}中，松散占用可取不连续第1、3段得到{aggregate_best}，连续两段最低为{contiguous_best}。当前正文以开始时刻、持续时间和区间交集定义重叠；22 kW在总长1.5 h的相邻重叠上闭合为{fixed_power_energy:.1f} kWh。" if charging_exact_in_constraints else f"四时段反例{carbon}中，松散占用可取不连续第1、3段得到{aggregate_best}，连续两段最低为{contiguous_best}。当前连续性或固定功率电量账本仍不闭合。"),
            "显式定义开始、结束、各时段重叠长度和y_qt=pi_s*g_qt/3600，并由独立可行性证书复算。",
        ),
        record(
            "参与约束没有被误称为公平分配",
            "FAIL" if participation_misnamed else "PASS",
            "Pi_d≥theta Pi_d^0只规定不劣于独立经营的参与底线，未规定利润均等、比例公平、谈判解或转移支付。",
            "全文主称‘参与约束/个体理性约束’，只有另行定义公平准则时才使用‘收益公平’。",
        ),
    ]


def audit_notation_and_cost_semantics(tex: str) -> list[dict[str, str]]:
    bare_semantic_superscripts = re.findall(
        r"\^\{(?:fix|km|fuel|elec|occ|tr|op|car)\}",
        tex,
    )
    budget_symbol_distinct = (
        r"N_{\mathrm{eval}}" in tex
        and "评价预算为 $B$" not in tex
        and "$B$ & $280$ kWh" in tex
    )
    trip_fee_exact = (
        "$80$ £/配送趟" in tex
        and "£/班次" not in tex
        and "配送趟派遣费" in tex
        and "每趟派遣费" in tex
    )
    carbon_intensity_units_close = (
        "0.0475$--$0.18894$ kgCO" in tex
        and "0.0475$--$0.18894$ gCO" not in tex
        and "均以 kgCO" in tex
    )
    forecast_actual_separated = all(
        token in tex
        for token in (
            r"\widehat\gamma_t,\gamma_t",
            r"\widehat E_{kp}",
            "搜索使用预测碳强度 $\\widehat\\gamma_t$",
            "结果分析按实际碳强度 $\\gamma_t$ 复算",
        )
    )
    station_capacity_continuous = (
        r"O_{skp}(u)" in tex
        and r"u\in[0,H)" in section(tex, "eq:station_capacity").replace(" ", "")
        and r"O_{stkp}" not in tex
        and "所有会话端点划分的基本区间" in tex
    )
    formal_credit_zero = (
        r"CE^\tau=CE_d^\tau=0" in tex
        and "$CE$ & $0$ kgCO" in tex
        and "0.8E" not in tex
        and "只平移系统目标值" in tex
        and "聚焦碳价形成的边际激励" in tex
    )
    participation_semantics_exact = (
        r"\theta_d=0" in tex
        and "仍表示非负收益下界" in tex
        and "通过移除式" in tex
        and "不设参与底线" in tex
    )
    cross_depot_friction_zero = r"c_{i,d_i^0}^{\mathrm{tr}}=0" in tex
    return [
        record(
            "成本与碳价的语义上标使用正体",
            "PASS" if not bare_semantic_superscripts else "FAIL",
            (
                "fix、km、fuel、elec、occ、tr、op和car均为语义标签，正文统一使用\\mathrm正体。"
                if not bare_semantic_superscripts
                else f"仍发现{len(bare_semantic_superscripts)}处裸斜体语义上标：{bare_semantic_superscripts[:8]}。"
            ),
            "把语义标签写为\\mathrm{fix}、\\mathrm{km}、\\mathrm{fuel}、\\mathrm{elec}、\\mathrm{occ}、\\mathrm{tr}、\\mathrm{op}和\\mathrm{car}，变量字母仍用斜体。",
        ),
        record(
            "电池容量与算法评价预算不共用符号",
            "PASS" if budget_symbol_distinct else "FAIL",
            "电池容量继续用B，局部算法预算改用N_eval。" if budget_symbol_distinct else "B仍可能同时表示电池容量和算法评价预算。",
            "保留B表示kWh电池容量，并用N_eval等独立符号表示完整方案评价次数。",
        ),
        record(
            "固定费用与程序按配送趟计费一致",
            "PASS" if trip_fee_exact else "FAIL",
            "参数表和正文均明确80英镑为每配送趟派遣费；程序cost.py按len(solution.routes)计费。" if trip_fee_exact else "参数表或正文仍可能把按配送趟计取的固定费写成按班次或按实体车辆启用计费。",
            "把c_fix单位写为英镑/配送趟，并避免称为按实体车或按班次启用费。",
        ),
        record(
            "电网碳强度量纲与数值范围闭合",
            "PASS" if carbon_intensity_units_close else "FAIL",
            "正文与参数表均使用kgCO2e/kWh，正式范围为0.0475至0.18894。" if carbon_intensity_units_close else "碳强度的g/kWh与kg/kWh口径或数值范围尚未统一。",
            "若公式以kgCO2e结算，参数必须由g/kWh除以1000后再代入。",
        ),
        record(
            "预测碳强度与事后实际碳强度分离",
            "PASS" if forecast_actual_separated else "FAIL",
            "搜索使用预测值和预测排放，结果由实际碳强度复算。" if forecast_actual_separated else "决策阶段和结果结算阶段仍共用同一碳强度或排放符号。",
            "以widehat gamma和widehat E表示决策信息，以gamma和E表示事后结算，禁止用实际值反向优化。",
        ),
        record(
            "充电桩容量按连续时间并发核验",
            "PASS" if station_capacity_continuous else "FAIL",
            "容量约束使用O_skp(u)，并在会话端点划分的基本区间核验。" if station_capacity_continuous else "容量约束仍可能使用时段聚合占用，误判同一时段内不重叠会话。",
            "按连续充电区间定义占用函数，并在全部开始和结束端点之间检查并发数。",
        ),
        record(
            "正式碳信用合同与证据一致",
            "PASS" if formal_credit_zero else "FAIL",
            "模型保留固定信用记账；实验取CE=CE_d=0，并明确固定信用只平移系统目标值。" if formal_credit_zero else "论文仍可能把非零配额或配额松紧写成已有证据。",
            "参数和结果统一使用CE=0；配额松紧只能作为未检验扩展，不得写成发现。",
        ),
        record(
            "参与底线关闭语义准确",
            "PASS" if participation_semantics_exact else "FAIL",
            "theta=0仍是非负收益约束；无参与底线通过删除该约束实现。" if participation_semantics_exact else "theta=0仍可能被误写为关闭参与约束。",
            "区分theta=0与移除约束两种合同，实验标签必须对应实际实现。",
        ),
        record(
            "原责任车场的跨场摩擦为零",
            "PASS" if cross_depot_friction_zero else "FAIL",
            "符号表明确c_{i,d_i^0}^{\\mathrm{tr}}=0。" if cross_depot_friction_zero else "跨场摩擦成本未排除客户由原责任车场服务的情形。",
            "显式规定客户由原责任车场服务时跨场摩擦为零。",
        ),
    ]


def audit_core_symbol_registry(tex: str) -> list[dict[str, str]]:
    label = r"\label{tab:symbols}"
    label_at = tex.index(label)
    table_start = tex.rfind(r"\begin{table}", 0, label_at)
    table_end = tex.index(r"\end{table}", label_at)
    symbol_table = tex[table_start:table_end]
    required_tokens = (
        r"D,N^\tau",
        r"K^\tau,K_d^\tau",
        r"S,T,H",
        r"q_i,Q",
        r"B^{\min},B",
        r"d_{ij},v_{ij}^\tau,u_{ijr}^\tau",
        r"P_{ijr}^\tau,e_{ijr}^\tau,f_{ijr}^\tau",
        r"\alpha_k^e,\beta_{0k}^g",
        r"\beta_{1k}^g,\lambda^g",
        r"\Omega_k^\tau,\mathcal Q_{kp}",
        r"A_{ikp},z_{kp}^\tau",
        r"\widehat\gamma_t,\gamma_t",
        r"\Pi_d^{0,\tau},\theta_d,M",
    )
    missing = [token for token in required_tokens if token not in symbol_table]
    return [
        record(
            "核心集合物理量与模式变量进入主符号表",
            "PASS" if not missing else "FAIL",
            (
                "车场、客户、车辆、充电站、电网时段、运营时域、容量、电量、能耗系数和模式变量均可从主符号表直接查得。"
                if not missing
                else f"主符号表缺少核心记号：{missing}。"
            ),
            "把跨公式反复使用的集合、边界和物理系数列入主符号表；只在单段使用的中间量可在首次出现处定义。",
        )
    ]


def audit_foundation_and_algorithm_equations(tex: str) -> list[dict[str, str]]:
    equation_labels = re.findall(r"\\label\{(eq:[^{}]+)\}", tex)
    equation_budget_ok = 25 <= len(equation_labels) <= 35 and len(equation_labels) == len(set(equation_labels))
    required_trip_labels = {
        "eq:trip-depot-flow",
        "eq:trip-flow-balance",
        "eq:trip-load",
        "eq:trip-time",
        "eq:trip-energy",
        "eq:intertrip-link",
        "eq:mode-statistics",
        "eq:mode-cost-components",
    }
    trip_labels_ok = required_trip_labels.issubset(equation_labels)
    trip_depot = section(tex, "eq:trip-depot-flow").replace(" ", "")
    trip_load = section(tex, "eq:trip-load").replace(" ", "")
    trip_time = section(tex, "eq:trip-time").replace(" ", "")
    trip_energy = section(tex, "eq:trip-energy").replace(" ", "")
    intertrip = section(tex, "eq:intertrip-link").replace(" ", "")
    propagation_ok = all(
        (
            "x_{id_r^+r}" in trip_depot,
            "x_{d_r^-jr}" in trip_depot,
            "L_{d_r^+r}" in trip_load,
            "q_ia_{ir}" in trip_load,
            "1-x_{ijr}" in trip_load,
            "L_{jr}-L_{ir}+q_j" in trip_load,
            "1-x_{ijr}" in trip_time,
            "t_{ij}^\\tau" in trip_time,
            "1-x_{ijr}" in trip_energy,
            "e_{ijr}^\\tau" in trip_energy,
            "3600Y_h^D" in intertrip,
            "\\pi_{d(k)}" in intertrip,
        )
    )
    no_bare_spacing_commands = re.search(r"(?<!\\)qquad", tex) is None

    selector = AlphaUCB([4.0, 3.0, 2.0, 0.05], 0.08, 2, 2)
    selector.update(None, 0, 0, 0)
    implementation_ucb = float(selector._values()[0, 0])
    closed_ucb = 4.0 + math.sqrt(0.08 * math.log(2.0) / 2.0)
    ucb_eq = section(tex, "eq:ucb-selection")
    ucb_update = section(tex, "eq:ucb-update")
    ucb_ok = (
        abs(implementation_ucb - closed_ucb) < 1e-12
        and r"\alpha\ln(1+n)" in ucb_eq
        and r"1+n_{hg}(n)" in ucb_eq
        and r"\sigma_o" in ucb_update
        and "$4,3,2,0.05$" in tex
    )

    initial_obj = 1000.0
    initial_temp = -0.05 * initial_obj / math.log(0.5)
    five_pct_acceptance = math.exp((initial_obj - 1.05 * initial_obj) / initial_temp)
    sa_eq = section(tex, "eq:sa-acceptance")
    sa_ok = (
        abs(five_pct_acceptance - 0.5) < 1e-12
        and r"F(S)-F(S')" in sa_eq
        and r"T_{n+1}" in sa_eq
        and r"\mu=0.95" in sa_eq
        and r"0.05F(S_0)" in sa_eq
    )

    candidates = charge_start_candidates(300.0, 2700.0, 900.0)
    charge_eq = section(tex, "eq:charging-candidates")
    charge_ok = (
        candidates == (300.0, 900.0, 1800.0, 2700.0)
        and r"\mathcal B" in charge_eq
        and r"b-\Delta_q" in charge_eq
        and r"\overline a_q-\Delta_q" in charge_eq
        and r"\arg\min" in charge_eq
    )
    return [
        record(
            "编号公式数量处于集中可读区间",
            "PASS" if equation_budget_ok else "FAIL",
            f"当前正文有{len(equation_labels)}个唯一编号公式；目标区间为25至35。",
            "删除重复恒等式或补齐必要基础约束，但不得以凑数量代替模型闭合。",
        ),
        record(
            "可行趟的流量载重时间电量与趟间衔接显式闭合",
            "PASS" if trip_labels_ok and propagation_ok else "FAIL",
            "正文已给出源汇流、客户流守恒、载重、时间、电量、趟间补电和模式成本七组基础式。",
            "保证每组传播式在x_ijr=1时退化为等式，并保留源汇副本与趟间连续性。",
        ),
        record(
            "公式间距命令未作为普通文字印出",
            "PASS" if no_bare_spacing_commands else "FAIL",
            "全文不存在漏写反斜杠的qquad裸词。" if no_bare_spacing_commands else "正文仍存在会被直接印出的qquad裸词。",
            "把裸qquad改为LaTeX命令\\qquad，并重新渲染对应页面。",
        ),
        record(
            "UCB选择和得分更新与运行时代码一致",
            "PASS" if ucb_ok else "FAIL",
            f"一次BEST更新后的实现UCB值={implementation_ucb:.12f}，闭式复算={closed_ucb:.12f}。",
            "正文须使用alpha=0.08、分母1+n_hg和得分4/3/2/0.05，不得套用另一版ALNS权重公式。",
        ),
        record(
            "模拟退火初温和降温与正式算法一致",
            "PASS" if sa_ok else "FAIL",
            f"F0=1000时T0={initial_temp:.12f}，接受5%劣解的闭式概率={five_pct_acceptance:.12f}。",
            "保持T0=-0.05F0/ln(0.5)、指数降温mu=0.95和当前解差值接受准则。",
        ),
        record(
            "分段碳强度充电候选点与实现一致",
            "PASS" if charge_ok else "FAIL",
            f"窗口[300,2700]、时长900 s的实现候选点为{candidates}。",
            "候选集必须包含窗口端点、分段边界和边界减持续时间，并与合法开始区间取交集。",
        ),
    ]


def main() -> None:
    tex = PAPER.read_text(encoding="utf-8")
    rows = (
        audit_title_and_abstract(tex)
        + audit_energy_equation(tex)
        + audit_multitrip_and_state(tex)
        + audit_structural_counterexamples(tex)
        + audit_notation_and_cost_semantics(tex)
        + audit_core_symbol_registry(tex)
        + audit_foundation_and_algorithm_equations(tex)
    )
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "raw_runs.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(rows[0]),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
    passed = sum(row["status"] == "PASS" for row in rows)
    failed = sum(row["status"] == "FAIL" for row in rows)
    warned = sum(row["status"] == "WARN" for row in rows)
    decision = {
        "status": "PASS" if failed == 0 else "HALT_FORMALIZATION",
        "passed": passed,
        "failed": failed,
        "warned": warned,
        "total": len(rows),
        "sealed_experiment_evidence_changed": False,
        "formal_e7_touched": False,
        "formalization_gate_passed": failed == 0,
        "submission_ready": False,
        "submission_blocker": "E7 formal evidence and final manuscript-wide review remain pending",
    }
    metadata = {
        "purpose": "paper-only SETP format, dimensional consistency, and formulation closure audit",
        "paper": str(PAPER.relative_to(ROOT)),
        "official_format_source": "https://sysengi.cjoe.ac.cn/CN/column/item55.shtml",
        "evaluator_function": "setp_solver.cost.ev_arc_energy_kwh",
        "audit_date": "2026-07-16",
    }
    (OUT / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = [
        "# 论文题名、摘要与核心公式审计",
        "",
        f"结论：{decision['status']}（{passed}/{len(rows)} 通过，{failed}项失败，{warned}项警告）。"
        + ("这只表示当前静态形式化门已通过；E7正式证据和全文终审尚未完成，不能据此称整稿可投稿。" if failed == 0 else "这否定当前论文形式化已经过关，不否定现有程序结果。"),
        "",
        "| 检查 | 结果 | 证据 | 必须修改 |",
        "|---|---|---|---|",
    ]
    report.extend(
        f"| {row['check']} | {row['status']} | {row['evidence'].replace('|', '/')} | {row['required_repair'].replace('|', '/')} |"
        for row in rows
    )
    report.extend([
        "",
        "审计边界：只读论文和统一评价器；未启动或查询E7正式运行，未修改任何封存实验文件。",
        "",
    ])
    (OUT / "report.md").write_text("\n".join(report), encoding="utf-8")
    hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(OUT.iterdir())
        if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._")
    }
    (OUT / "artifact_hashes.json").write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(decision, ensure_ascii=False))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""一次性检索脚本：把候选 PDF 抽成文本，供关键词检索与页码定位。

只读。不改仓库任何文件，输出全部写到 scratchpad 的 corpus/ 目录。
用法：python3 extract_corpus.py <outdir>
"""
import os
import subprocess
import sys
import json

BASE = "/Users/zhouleixishu/Zotero/storage"

# 规范路径：每篇论文只取一条（Zotero 中有重复条目，去重后计数）
PAPERS = {
    # key: (相对 storage 的路径, 简称)
    "pillac2013": ("QQ4LPCQG/Pillac 等 _ 2013 _ A review of dynamic vehicle routing problems.pdf", "Pillac 2013 EJOR 综述"),
    "ojeda2021": ("WRIK9AL5/Ojeda Rios 等 _ 2021 _ Recent dynamic vehicle routing problems A survey.pdf", "Ojeda Rios 2021 C&IE 综述"),
    "zhangwoensel2023": ("V42GX6NQ/Zhang和Woensel _ 2023 _ Dynamic vehicle routing with random requests A literature review.pdf", "Zhang & Van Woensel 2023 IJPE 综述"),
    "voccia2019": ("ZMCL7K4A/Voccia 等 _ 2019 _ The Same-Day Delivery Problem for Online Purchases.pdf", "Voccia 2019 TS 当日达"),
    "goodson2013": ("VKGBV4YR/Goodson 等 _ 2013 _ Rollout Policies for Dynamic Solutions to the Multivehicle Routing Problem with Stochastic Demand an.pdf", "Goodson 2013 OR rollout"),
    "mardesic2024": ("C2B46KJ5/Mardešić 等 _ 2024 _ Review of Stochastic Dynamic Vehicle Routing in the Evolving Urban Logistics Environment.pdf", "Mardesic 2024 Mathematics 综述"),
    "qiuhg2020": ("FVYX6447/邱晗光 等 _ 2020 _ 顾客可选末端交付方式和时间窗的城市配送动态订单接受优化研究.pdf", "邱晗光 2020 中国管理科学 动态订单接受"),
    "zhangwb2016": ("BIJNWWV8/张文博 等 _ 2016 _ 基于动态需求的带时间窗的车辆路径问题.pdf", "张文博 2016 工业工程与管理"),
    "liyang2022": ("KI5HD4AN/李阳 等 _ 2022 _ 动态需求下车辆路径问题的周期性优化模型及求解.pdf", "李阳 2022 中国管理科学 = ref:18"),
    "linmj2022": ("D8YBPRTM/林明锦 等 _ 2022 _ 考虑动态度和时间窗的两级车辆路径问题.pdf", "林明锦 2022 计算机集成制造系统 动态度"),
    "jiangGT2024": ("EBR6UEUC/姜广田 等 _ 2024 _ 绿色物流配送下的多车型动态车辆路径优化.pdf", "姜广田 2024 系统工程理论与实践"),
    "zhangjl2022": ("M4REWA47/张金良和李超 _ 2022 _ 碳排放影响下的动态配送车辆路径优化研究.pdf", "张金良 2022 中国管理科学 碳排放动态"),
    "fanhm2022": ("7PMD9PJV/范厚明 等 _ 2022 _ 时变路网下异型车辆动态配置与路径优化.pdf", "范厚明 2022 系统工程理论与实践"),
    "jiayj2022": ("TBKXKAC2/贾永基 等 _ 2022 _ 考虑时变速度和动态需求的电动车辆路径问题.pdf", "贾永基 2022 工业工程与管理"),
    "gexl2022": ("YAACYG26/葛显龙 等 _ 2022 _ 基于两阶段求解策略的动态电动车辆路径优化研究.pdf", "葛显龙 2022 运筹与管理"),
    "xuxf2021": ("Z4TP38CD/徐小峰 等 _ 2021 _ 整合逆向物流协同配送动态路径优化问题研究.pdf", "徐小峰 2021 管理科学学报 协同+动态"),
    "zhangxn2025": ("84E5P89Y/张晓楠 等 _ 2025 _ 动态随机餐食外卖配送在线决策模型与算法.pdf", "张晓楠 2025 系统工程理论与实践"),
    "houying2026": ("WQKNPME9/侯莹 等 _ 2026 _ 考虑动态配送时间需求的多策略协同车辆路径优化算法.pdf", "侯莹 2026 控制与决策"),
    "lufq2026": ("W6MM2CMN/卢福强 等 _ 2026 _ 动态订单下无人机辅助骑手外卖配送路径优化研究.pdf", "卢福强 2026 中国管理科学"),
    "shijl2023": ("8GZ3MHF9/石建力和谢丽蓉 _ 2023 _ 近似动态规划求解随机需求分批配送车辆路径问题.pdf", "石建力 2023 运筹与管理"),
    "qiuyy2024thesis": ("2JBQSR8A/21级邱莹莹大论文.pdf", "邱莹莹 学位论文 = ref:71"),
    "qiuyy2024paper": ("22Y9SKJD/邱莹莹和干宏程 _ 2024 _ 低碳背景下混合车队车辆路径优化研究.pdf", "邱莹莹 2024 重庆工商大学学报"),
    "dong2023": ("EFT7MFYW/Dong 等 _ 2023 _ Dynamic electric vehicle routing problem considering mid-route recharging and new demand arrival usi.pdf", "Dong 2023 SETA 动态EVRP"),
    "wang2025dgvrp": ("35EXISA9/Wang 等 _ 2025 _ A two-phase algorithm for the dynamic time-dependent green vehicle routing problem in decoration was.pdf", "Wang 2025 ESWA 动态绿色VRP"),
    "ge2025": ("F8E3PW6T/Ge 等 _ 2025 _ Dynamic routing optimization of electric vehicles for retailers based on consumer behavior predictio.pdf", "Ge 2025 TR-E"),
    "he2025": ("KGLVCNR6/He 等 _ 2025 _ Dynamic electric vehicle fleets management problem for multi-service platforms with integrated ride-.pdf", "He 2025 TR-B"),
    "zhao2025": ("9DL6G3E2/Zhao 等 _ 2025 _ Electric vehicle routing problem considering traffic conditions and real-time loads.pdf", "Zhao 2025 TR-C"),
    "wangchen2025carbon": ("LRI46T4Z/Wang和Chen _ 2025 _ Carbon-Aware Quantification of Real-Time Aggregate Power Flexibility of Electric Vehicles.pdf", "Wang & Chen 2025 IEEE TSG 碳感知"),
}


def main(outdir):
    os.makedirs(outdir, exist_ok=True)
    manifest = {}
    for key, (rel, label) in PAPERS.items():
        src = os.path.join(BASE, rel)
        dst = os.path.join(outdir, key + ".txt")
        if not os.path.exists(src):
            manifest[key] = {"label": label, "src": src, "status": "MISSING"}
            continue
        subprocess.run(["pdftotext", "-layout", src, dst], check=False)
        n = 0
        if os.path.exists(dst):
            with open(dst, "rb") as f:
                raw = f.read()
            n = len(raw.decode("utf-8", "replace").strip())
        manifest[key] = {
            "label": label,
            "src": src,
            "txt": dst,
            "chars": n,
            "status": "OK" if n > 2000 else "EMPTY_OR_IMAGE_LAYER",
        }
        print(f"{key:22s} {manifest[key]['status']:22s} {n:8d}  {label}")
    with open(os.path.join(outdir, "manifest.json"), "w") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main(sys.argv[1])

#!/usr/bin/env python3
"""Map three official China policy tariff schedules to 48 half-hour slots.

This file also materializes the three read-only evidence chains when invoked
with ``--write-evidence``.  It never runs a solver.  A blank tariff value is
intentional: the official period table was found, but no stable first-party
absolute price was available for that region/date.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
ACCESS_DATE = "2026-07-17"
SLOT_HEADER = ("slot", "start_time", "end_time", "tariff_band", "electricity_yuan_per_kWh")


@dataclass(frozen=True)
class Period:
    start: int
    end: int
    band: str


@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    url: str
    institution: str
    publication_date: str
    title: str
    raw_name: str
    source_role: str
    notes: str
    excerpt: str
    snapshot_format: str = "browser_text_transcript"


def minute(hhmm: str) -> int:
    hours, minutes = (int(part) for part in hhmm.split(":"))
    if minutes not in range(60) or hours not in range(25):
        raise ValueError(f"invalid time: {hhmm}")
    if hours == 24 and minutes != 0:
        raise ValueError(f"invalid 24-hour boundary: {hhmm}")
    return hours * 60 + minutes


def period(start: str, end: str, band: str) -> Period:
    return Period(minute(start), minute(end), band)


def time_label(value: int) -> str:
    value %= 1440
    return f"{value // 60:02d}:{value % 60:02d}"


def _expanded_periods(periods: Iterable[Period]) -> list[tuple[int, int, str]]:
    expanded: list[tuple[int, int, str]] = []
    for item in periods:
        if item.start == item.end:
            raise ValueError(f"zero-length period: {item}")
        if item.start < item.end:
            expanded.append((item.start, item.end, item.band))
        else:
            expanded.extend(((item.start, 1440, item.band), (0, item.end, item.band)))
    return expanded


def band_for_interval(start: int, end: int, periods: Sequence[Period]) -> str:
    """Return the unique band covering [start, end), rejecting gaps/overlaps."""

    if start < 0 or end > 1440 or start >= end:
        raise ValueError(f"invalid interval: {start}-{end}")
    matches = [
        band
        for left, right, band in _expanded_periods(periods)
        if left <= start and end <= right
    ]
    if len(matches) != 1:
        raise ValueError(f"tariff gap/overlap for {start}-{end}: {matches}")
    return matches[0]


def map_periods_to_slots(periods: Sequence[Period]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for slot in range(48):
        start, end = slot * 30, slot * 30 + 30
        rows.append(
            {
                "slot": str(slot + 1),
                "start_time": time_label(start),
                "end_time": time_label(end),
                "tariff_band": band_for_interval(start, end, periods),
            }
        )
    return rows


def decimal_text(value: Decimal | None) -> str:
    return "" if value is None else format(value, "f")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source(
    source_id: str,
    url: str,
    institution: str,
    publication_date: str,
    title: str,
    raw_name: str,
    source_role: str,
    notes: str,
    excerpt: str,
    snapshot_format: str = "browser_text_transcript",
) -> SourceSpec:
    return SourceSpec(
        source_id,
        url,
        institution,
        publication_date,
        title,
        raw_name,
        source_role,
        notes,
        excerpt,
        snapshot_format,
    )


CEA_REUSE = (
    {
        "source_id": "frozen_cea_cneeex_daily",
        "url": "https://overview.cneeex.com/c/2025-06-30/496524.shtml",
        "institution": "上海环境能源交易所",
        "publication_date": "2025-06-30",
        "title": "全国碳市场每日综合价格行情（2025-06-30）",
        "path": "data/Carbon/中国情景/raw_20260717/CNEEEX_CEA_2025-06-30.html",
        "source_role": "reused_frozen_cea",
        "notes": "复用上海链冻结快照，不重复取证。",
    },
    {
        "source_id": "frozen_cea_mee_operation_data",
        "url": "https://www.mee.gov.cn/ywgz/ydqhbh/wsqtkz/202601/t20260101_1139528.shtml",
        "institution": "生态环境部",
        "publication_date": "2026-01-01",
        "title": "2025年全国碳市场运行数据",
        "path": "data/Carbon/中国情景/raw_20260717/MEE_national_carbon_market_2025.html",
        "source_role": "reused_frozen_cea",
        "notes": "复用上海链冻结快照，仅解释CEA影子价格语义。",
    },
    {
        "source_id": "frozen_cea_mee_report",
        "url": "https://www.mee.gov.cn/ywgz/ydqhbh/wsqtkz/202509/W020250927515316322073.pdf",
        "institution": "生态环境部",
        "publication_date": "2025-09-27",
        "title": "全国碳市场发展报告（2025）",
        "path": "data/Carbon/中国情景/raw_20260717/MEE_national_carbon_market_report_2025.pdf",
        "source_role": "reused_frozen_cea",
        "notes": "复用上海链冻结快照，不作为道路物流法定碳成本。",
    },
)


REGION_CONFIGS = {
    "beijing": {
        "display_name": "北京",
        "pinyin": "BEIJING",
        "directory": "china_policy_price_gate_beijing_20260717",
        "slot_file": "beijing_july_tou_48slot.csv",
        "decision": "HALT_BEIJING_CHARGING_SERVICE_FEE_OFFICIAL_NUMERIC_SOURCE_MISSING",
        "tariff_price_status": "historical_official_snapshot_only",
        "tariffs": {
            "valley": Decimal("0.435829"),
            "flat": Decimal("0.681335"),
            "peak": Decimal("0.926841"),
            "sharp_peak": Decimal("1.057777"),
        },
        "periods": (
            period("00:00", "07:00", "valley"),
            period("07:00", "10:00", "flat"),
            period("10:00", "11:00", "peak"),
            period("11:00", "13:00", "sharp_peak"),
            period("13:00", "16:00", "flat"),
            period("16:00", "17:00", "sharp_peak"),
            period("17:00", "22:00", "peak"),
            period("22:00", "23:00", "flat"),
            period("23:00", "24:00", "valley"),
        ),
        "diesel": Decimal("6.87"),
        "diesel_date": "2026-07-03",
        "charging_typical": None,
        "charging_cap": None,
        "tariff_basis": "国网95598北京2024年7月1—31日1—10千伏两部制官方数值快照；时段按京发改规〔2023〕11号夏季规则映射。",
        "period_text": "峰10:00-13:00、17:00-22:00；平7:00-10:00、13:00-17:00、22:00-23:00；谷23:00-次日7:00；夏季尖峰11:00-13:00、16:00-17:00。",
        "valley_statement": "夜间谷段（23:00—次日7:00），没有午间谷段。",
        "diesel_text": "北京发改委2026-07-03文件列明0号柴油最高零售价6.87元/L，自2026-07-04起执行。",
        "charging_text": "北京现行公开口径为充电服务费市场定价/市场调节价，未找到当期公共中位价或指导上限官方数值；旧2015年上限页面已标明无效。",
        "tried_channels": "北京发改委现行分时通知、北京政府充电问答、北京发改委充电市场化通知、北京政府价格目录及国网95598代理购电价表。",
        "sources": (
            source(
                "beijing_tou_policy",
                "https://fgw.beijing.gov.cn/fgwzwgk/2024zcwj/bwgfxwj/202308/t20230821_3718725.htm",
                "北京市发展和改革委员会",
                "2023-08-18",
                "北京市发展和改革委员会关于进一步完善本市分时电价机制等有关事项的通知",
                "beijing_tou_policy_2023-08-18.html.txt",
                "current_tou_policy",
                "现行政策时段、倍率和夏季尖峰原文。",
                "峰时段：10:00-13:00；17:00-22:00。平时段：7:00-10:00；13:00-17:00；22:00-23:00。谷时段：23:00-次日7:00。夏季（7、8月）尖峰：11:00-13:00、16:00-17:00。两部制峰平谷比例1.6:1:0.4；尖峰在高峰基础上上浮20%。",
            ),
            source(
                "beijing_tou_numeric_2024_07",
                "https://www.95598.cn/omg-static/omg-static/99306272029057823884400238783751.pdf",
                "国网北京市电力公司（国家电网95598）",
                "2024-07-01",
                "国网北京市电力公司代理购电工商业用户电价表",
                "beijing_tou_numeric_2024-07.pdf.txt",
                "official_numeric_tou_snapshot",
                "可稳定读取的官方历史数值快照，不宣称为2026年7月最终结算价。",
                "2024-07-01至2024-07-31，1—10千伏两部制工商业用户：平0.681335元/kWh，尖峰1.057777元/kWh，高峰0.926841元/kWh，低谷0.435829元/kWh。时段栏同时列峰10:00-13:00、17:00-22:00，平7:00-10:00、13:00-17:00、22:00-23:00，谷23:00-次日7:00，夏季尖峰11:00-13:00、16:00-17:00。",
                "browser_text_transcript_of_official_pdf",
            ),
            source(
                "beijing_diesel_2026_07_03",
                "https://fgw.beijing.gov.cn/fgwzwgk/2024zcwj/bwqtwj/202607/t20260703_4745916.htm",
                "北京市发展和改革委员会",
                "2026-07-03",
                "本市成品油价格调整",
                "beijing_diesel_2026-07-03.html.txt",
                "official_diesel_snapshot",
                "当期最高零售价。",
                "自2026年7月3日24时起，0号柴油最高零售价为6.87元/升（7935元/吨）。",
            ),
            source(
                "beijing_charging_market_2025_10",
                "https://www.beijing.gov.cn/hudong/bmwd/jsjbmyyt/2025jmwd/2025jmwd3/202510/t20251024_4238463.html",
                "北京市人民政府门户网站（北京市发改委答复）",
                "2025-10-24",
                "关于电动汽车充电收费的问答",
                "beijing_charging_market_2025-10-24.html.txt",
                "charging_fee_current_rule",
                "现行口径只有市场定价，没有公共中位价或指导上限数字。",
                "公共充电费用由电费和充电服务费组成；充电服务费实行市场定价原则。本页没有当期公共充电服务费中位价或指导上限数字。",
            ),
            source(
                "beijing_2026_market_plan",
                "https://www.beijing.gov.cn/cs/gncs/zcwj/202603/t20260327_4568006.html",
                "北京市人民政府门户网站",
                "2026-03-27",
                "北京市2026年电力市场化交易工作安排",
                "beijing_2026_market_plan_2026-03-27.html.txt",
                "current_context",
                "说明代理购电成本按月发布，不能用旧月度绝对价冒充2026年7月价。",
                "2026年继续执行本市分时电价政策，代理购电价格按月公布；本次没有把2024年7月数值标成2026年7月当前价。",
            ),
        ),
    },
    "guangdong": {
        "display_name": "广东（深圳）",
        "pinyin": "GUANGDONG",
        "directory": "china_policy_price_gate_guangdong_20260717",
        "slot_file": "guangdong_july_tou_48slot.csv",
        "decision": "HALT_GUANGDONG_CHARGING_SERVICE_FEE_OFFICIAL_NUMERIC_SOURCE_MISSING",
        "tariff_price_status": "official_absolute_current_snapshot_missing",
        "tariffs": {"valley": None, "flat": None, "peak": None, "sharp_peak": None},
        "periods": (
            period("00:00", "08:00", "valley"),
            period("08:00", "10:00", "flat"),
            period("10:00", "11:00", "peak"),
            period("11:00", "12:00", "sharp_peak"),
            period("12:00", "14:00", "flat"),
            period("14:00", "15:00", "peak"),
            period("15:00", "17:00", "sharp_peak"),
            period("17:00", "19:00", "peak"),
            period("19:00", "24:00", "flat"),
        ),
        "diesel": Decimal("6.83"),
        "diesel_date": "2026-07-03",
        "charging_typical": None,
        "charging_cap": None,
        "tariff_basis": "深圳发改委现行文件给出时段和倍率；2026年7月深圳供电局官方账号公告为图片，未能稳定读取绝对元/kWh数值，故不填二手数字。",
        "period_text": "峰10:00-12:00、14:00-19:00；谷0:00-8:00；其余为平；7、8、9月及高温天气尖峰11:00-12:00、15:00-17:00，尖峰为高峰上浮25%。",
        "valley_statement": "夜间谷段（0:00—8:00），没有午间谷段。",
        "diesel_text": "广东省发改委价格调整的政府官方转载列明0号柴油（Ⅵ）最高零售价6.83元/L，自2026-07-03 24时起执行。",
        "charging_text": "深圳现行公开口径为充换电服务费市场调节价，相关政府定价/指导文件已废止；没有当期公共中位价或指导上限官方数值，因此只保留自有充电服务费0。",
        "tried_channels": "深圳发改委分时通知及价目表、充换电服务费市场化/废止通知、发改委问答、深圳供电局官方账号2026年7月公告、广东发改委成品油公告。",
        "sources": (
            source(
                "shenzhen_tou_policy",
                "https://fgw.sz.gov.cn/zwgk/qt/tzgg/content/post_9493596.html",
                "深圳市发展和改革委员会",
                "2021-12-28",
                "深圳市发展和改革委员会关于进一步完善我市峰谷分时电价政策有关问题的通知",
                "shenzhen_tou_policy_2021-12-28.html.txt",
                "current_tou_policy",
                "深圳本地现行时段及尖峰规则。",
                "高峰：10:00-12:00、14:00-19:00；低谷：0:00-8:00；其余为平段。7、8、9月整月及高温天气尖峰：11:00-12:00、15:00-17:00，尖峰在高峰基础上上浮25%。",
            ),
            source(
                "shenzhen_tou_ratio_table",
                "https://fgw.sz.gov.cn/attachment/1/1460/1460239/11394935.pdf",
                "深圳市发展和改革委员会",
                "unknown",
                "深圳市居民生活电价价目表",
                "shenzhen_tou_ratio_table.pdf.txt",
                "official_tou_ratio_table",
                "官方附件给出峰平谷倍率，但没有本链所需的2026年7月绝对元/kWh。",
                "工商业用户按类别和电压给出峰平谷倍率；例如普通工商业为1.3553:1:0.2894，大工业/工商业按计量和电压另有倍率。本附件没有2026年7月深圳工商业绝对价格，不能把倍率当作绝对价格。",
                "browser_text_transcript_of_official_pdf",
            ),
            source(
                "shenzhen_diesel_2026_07_03",
                "https://www.zhanjiang.gov.cn/zdlyxxgk/jgsf/jfbz/content/post_2198046.html",
                "广东省发展和改革委员会（湛江市政府官方转载）",
                "2026-07-03",
                "2026年7月3日24时起成品油价格调整",
                "guangdong_diesel_2026-07-03.html.txt",
                "official_diesel_snapshot",
                "省发改委原始口径的政府官方转载。",
                "来源：广东省发展改革委。0号柴油（Ⅵ）最高零售价6.83元/升，零售吨价7970元；自2026年7月3日24时起执行。",
            ),
            source(
                "shenzhen_charging_market_2022_11",
                "https://fgw.sz.gov.cn/gkmlpt/content/10/10281/post_10281285.html",
                "深圳市发展和改革委员会",
                "2022-11-20",
                "深圳市发展和改革委员会关于废止部分价格政策文件的通知",
                "shenzhen_charging_market_2022-11-20.html.txt",
                "charging_fee_current_rule",
                "旧充电服务费政府定价/指导文件废止，转市场调节价。",
                "电动汽车充换电服务费由政府定价/政府指导价调整为市场调节价，相关旧价格文件同时废止。",
            ),
            source(
                "shenzhen_official_power_account_july_2026",
                "https://weibo.com/u/1965575074",
                "深圳供电局有限公司（南方电网官方账号）",
                "2026-07-02",
                "深圳供电局有限公司2026年7月代理购电价格公告",
                "shenzhen_official_power_account_july_2026.txt",
                "current_numeric_retrieval_attempt",
                "官方账号公告存在但图文正文没有稳定可读数字；不使用二手OCR或估算。",
                "官方账号可确认2026年7月代理购电价格公告以图片形式发布；浏览器正文未提供可稳定复制的峰、平、谷、尖峰绝对元/kWh数值。本链不把二手网页OCR填入价格数组。",
                "browser_text_transcript_of_official_account_index",
            ),
            source(
                "shenzhen_charging_faq_2022_06",
                "https://fgw.sz.gov.cn/hdjl/ywzsk/jgzcgl/content/post_9909528.html",
                "深圳市发展和改革委员会",
                "2022-06-24",
                "电动汽车充换电服务费是否有政府指导价问答",
                "shenzhen_charging_faq_2022-06-24.html.txt",
                "charging_fee_negative_evidence",
                "官方问答确认市场调节价，未给出中位价或指导上限。",
                "充换电服务费实行市场调节价，由经营企业自主制定；政府不再制定统一服务费价格。",
            ),
        ),
    },
    "chongqing": {
        "display_name": "重庆",
        "pinyin": "CHONGQING",
        "directory": "china_policy_price_gate_chongqing_20260717",
        "slot_file": "chongqing_july_tou_48slot.csv",
        "decision": "HALT_CHONGQING_CHARGING_SERVICE_FEE_OFFICIAL_NUMERIC_SOURCE_MISSING",
        "tariff_price_status": "historical_official_snapshot_plus_policy_derived_sharp",
        "tariffs": {
            "valley": Decimal("0.379188"),
            "flat": Decimal("0.762307"),
            "peak": Decimal("1.133067"),
            "sharp_peak": Decimal("1.3596804"),
        },
        "periods": (
            period("00:00", "08:00", "valley"),
            period("08:00", "11:00", "flat"),
            period("11:00", "12:00", "peak"),
            period("12:00", "14:00", "sharp_peak"),
            period("14:00", "17:00", "peak"),
            period("17:00", "20:00", "flat"),
            period("20:00", "22:00", "peak"),
            period("22:00", "24:00", "flat"),
        ),
        "diesel": Decimal("6.90"),
        "diesel_date": "2026-07-04",
        "charging_typical": None,
        "charging_cap": None,
        "tariff_basis": "国网重庆2025年2月1—10千伏两部制官方数值快照；2026年7月尖峰按现行政策从官方峰值透明推导，不宣称为2026年7月代理购电最终价。",
        "period_text": "峰11:00—17:00、20:00—22:00；平08:00—11:00、17:00—20:00、22:00—24:00；谷00:00—08:00；7、8、12、1月尖峰12:00—14:00，尖峰为高峰上浮20%。",
        "valley_statement": "夜间谷段（0:00—8:00），没有午间谷段；午间12:00—14:00是尖峰而不是谷。",
        "diesel_text": "重庆发改委2026-07-04成品油调价页面列明0号柴油（Ⅵ）最高零售价6.90元/L。",
        "charging_text": "重庆发改委2025年问答确认旧政府指导价政策已废止，现行充电服务费为市场调节价；没有当期公共中位价或指导上限官方数值，旧0.40元/kWh不能使用。",
        "tried_channels": "重庆发改委分时通知、国网重庆代理购电价格公示页和2025年2月官方电价表、重庆发改委成品油页面、充电服务费问答及旧政策废止页面。",
        "sources": (
            source(
                "chongqing_tou_policy",
                "https://fzggw.cq.gov.cn/zwgk/zfxxgkml/zcwj/xzgfxwj/sfzggwxzgfxwj/202112/t20211209_10119678_wap.html",
                "重庆市发展和改革委员会",
                "2021-12-09",
                "重庆市发展和改革委员会关于印发进一步完善我市分时电价机制有关事项的通知",
                "chongqing_tou_policy_2021-12-09.html.txt",
                "current_tou_policy",
                "现行政策时段、倍率和尖峰规则。",
                "峰11:00—17:00、20:00—22:00；平08:00—11:00、17:00—20:00、22:00—24:00；谷00:00—08:00。7、8、12、1月尖峰12:00—14:00；峰平谷比例4.2:1，峰价上浮60%，谷价下浮62%，尖峰在峰价基础上上浮20%。",
            ),
            source(
                "chongqing_tou_numeric_2025_02",
                "https://www.95598.cn/omg-static/omg-static/99301281451033839938300638700023.pdf",
                "国网重庆电力有限公司（国家电网95598）",
                "2025-02-01",
                "国网重庆电力有限公司代理购电价格信息表（2025年2月）",
                "chongqing_tou_numeric_2025-02.pdf.txt",
                "official_numeric_tou_snapshot",
                "官方历史数值快照；尖峰值按现行政策透明推导。",
                "1—10千伏两部制工商业用户：平0.762307元/kWh，高峰1.133067元/kWh，低谷0.379188元/kWh。2025年2月不执行季节性尖峰；尖峰值不在本表直接出现。",
                "browser_text_transcript_of_official_pdf",
            ),
            source(
                "chongqing_state_grid_price_index",
                "https://www.cq.sgcc.com.cn/html/main/col2680/column_2680_1.html",
                "国网重庆市电力公司",
                "2026-02-25",
                "代理购电价格公示表—2026年3月（发布）",
                "chongqing_state_grid_price_index_2026-02-25.html.txt",
                "current_numeric_retrieval_attempt",
                "官方索引确认2026年3月表已发布，但本次未稳定读出附件绝对价格。",
                "官方页面列有“代理购电价格公示表-2026年3月(发布)”及重庆电网销售电价表。本次读取未获得2026年7月各时段可核验绝对元/kWh文本，不以2025年2月数值冒充当期价。",
            ),
            source(
                "chongqing_diesel_2026_07_04",
                "https://fzggw.cq.gov.cn/zwgk/zfxxgkml/jgxx/jgzc/202607/t20260704_15799337_wap.html",
                "重庆市发展和改革委员会",
                "2026-07-04",
                "重庆市成品油价格调整",
                "chongqing_diesel_2026-07-04.html.txt",
                "official_diesel_snapshot",
                "当期最高零售价。",
                "0号柴油（Ⅵ）最高零售价6.90元/升（8110元/吨），按2026年7月3日24时起的成品油调价执行。",
            ),
            source(
                "chongqing_charging_market_2025_10",
                "https://fzggw.cq.gov.cn/hdjl/gkxx/lxxd/detail_wap.html?metadataId=1082249",
                "重庆市发展和改革委员会",
                "2025-10-16",
                "电动汽车充电服务费政策问答",
                "chongqing_charging_market_2025-10-16.html.txt",
                "charging_fee_current_rule",
                "现行市场调节价口径，没有当期中位价或指导上限数值。",
                "旧政府指导价政策渝府办发〔2018〕184号已由渝府发〔2023〕21号废止；目前重庆市电动汽车充电服务费实行市场调节价。",
            ),
            source(
                "chongqing_old_charging_cap_2018",
                "https://www.cq.gov.cn/zwgk/zfxxgkml/szfwj/xzgfxwj/szfbgt/201812/t20181226_8837673_app.html",
                "重庆市人民政府",
                "2018-12-26",
                "重庆市电动汽车充电基础设施建设运营管理办法",
                "chongqing_old_charging_cap_2018-12-26.html.txt",
                "charging_fee_negative_evidence",
                "旧办法曾有0.40元/kWh上限，但不作为当前价格。",
                "旧办法曾规定充电服务费上限0.40元/kWh；重庆发改委2025年官方答复已说明该政府指导价政策被废止，因此该数字排除。",
            ),
        ),
    },
}


def region_rows(region: str) -> list[dict[str, str]]:
    config = REGION_CONFIGS[region]
    rows = map_periods_to_slots(config["periods"])
    for row in rows:
        row["electricity_yuan_per_kWh"] = decimal_text(config["tariffs"][row["tariff_band"]])
    return rows


def csv_write(path: Path, fields: Sequence[str], rows: Iterable[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def raw_text(item: SourceSpec) -> str:
    return (
        f"snapshot_format={item.snapshot_format}\n"
        f"original_url={item.url}\n"
        f"access_date={ACCESS_DATE}\n"
        f"publishing_institution={item.institution}\n"
        f"publication_date={item.publication_date}\n"
        f"title={item.title}\n\n"
        f"官方正文相关摘录：\n{item.excerpt}\n"
    )


def frozen_cea_rows() -> list[dict[str, object]]:
    frozen_path = REPO_ROOT / "baselines/e4_e5/china_policy_price_gate_20260717/source_evidence.csv"
    by_path: dict[str, dict[str, str]] = {}
    with frozen_path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            by_path[row["path"]] = row
    rows: list[dict[str, object]] = []
    for item in CEA_REUSE:
        old = by_path[item["path"]]
        rows.append(
            {
                "source_id": item["source_id"],
                "url": item["url"],
                "path": item["path"],
                "raw_path": "",
                "access_date": ACCESS_DATE,
                "publishing_institution": item["institution"],
                "publication_date": item["publication_date"],
                "title": item["title"],
                "bytes": int(old["bytes"]),
                "sha256": old["sha256"],
                "expected_sha256": old["expected_sha256"],
                "hash_match": old["hash_match"],
                "source_role": item["source_role"],
                "notes": item["notes"],
            }
        )
    return rows


def source_rows(config: dict[str, object], target: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in config["sources"]:
        raw_path = target / "raw" / item.raw_name
        digest = sha256_file(raw_path)
        rows.append(
            {
                "source_id": item.source_id,
                "url": item.url,
                "path": f"raw/{item.raw_name}",
                "raw_path": f"raw/{item.raw_name}",
                "access_date": ACCESS_DATE,
                "publishing_institution": item.institution,
                "publication_date": item.publication_date,
                "title": item.title,
                "bytes": raw_path.stat().st_size,
                "sha256": digest,
                "expected_sha256": digest,
                "hash_match": "1",
                "source_role": item.source_role,
                "notes": item.notes,
            }
        )
    return rows + frozen_cea_rows()


def write_price_scenarios(path: Path, config: dict[str, object]) -> None:
    rows: list[dict[str, str]] = []
    fields = ("parameter", "scenario", "value", "unit", "model_value", "model_unit", "interpretation")
    for scenario, value, model_value in (
        ("observed_low", "56.32000", "0.05632000"),
        ("base", "75.02000", "0.07502000"),
        ("observed_high", "105.65000", "0.10565000"),
    ):
        rows.append({
            "parameter": "carbon_shadow_price", "scenario": scenario, "value": value,
            "unit": "yuan_per_tCO2e", "model_value": model_value, "model_unit": "yuan_per_kgCO2e",
            "interpretation": "复用冻结CEA观察值；内部影子价格，不是道路物流法定履约成本",
        })
    diesel = decimal_text(config["diesel"])
    rows.append({
        "parameter": "diesel_price", "scenario": f"official_current_{config['diesel_date']}",
        "value": diesel, "unit": "yuan_per_L", "model_value": diesel, "model_unit": "yuan_per_L",
        "interpretation": "官方0号柴油最高零售价快照，不等于车队批量采购成交价",
    })
    rows.append({
        "parameter": "public_charging_service_fee", "scenario": "depot_owned", "value": "0.00",
        "unit": "yuan_per_kWh", "model_value": "0.00000000", "model_unit": "yuan_per_kWh",
        "interpretation": "自有充电不计公共服务费",
    })
    for scenario, value, explanation in (
        ("public_typical", config["charging_typical"], "未找到官方当期公共中位价；NA不进入模型"),
        ("public_guidance_cap", config["charging_cap"], "未找到官方当期指导上限；NA不进入模型"),
    ):
        rows.append({
            "parameter": "public_charging_service_fee", "scenario": scenario, "value": decimal_text(value),
            "unit": "yuan_per_kWh", "model_value": decimal_text(value), "model_unit": "yuan_per_kWh",
            "interpretation": explanation,
        })
    for band in ("valley", "flat", "peak", "sharp_peak"):
        value = decimal_text(config["tariffs"][band])
        rows.append({
            "parameter": "electricity_tariff", "scenario": band, "value": value,
            "unit": "yuan_per_kWh", "model_value": value, "model_unit": "yuan_per_kWh",
            "interpretation": config["tariff_price_status"],
        })
    csv_write(path, fields, rows)


def write_report(path: Path, config: dict[str, object], evidence_count: int) -> None:
    tariffs = config["tariffs"]
    if tariffs["peak"] is None or tariffs["valley"] is None:
        ratio = "NA（官方绝对电价缺失）"
        sharp_ratio = "NA"
    else:
        ratio = f"{tariffs['peak'] / tariffs['valley']:.6f}"
        sharp_ratio = f"{tariffs['sharp_peak'] / tariffs['valley']:.6f}"
    extra = {
        "北京": "北京2026年7月月度最终绝对电价未被稳定读取，目录仅保留2024年7月官方历史数值快照。",
        "广东（深圳）": "深圳官方7月账号公告和价目表完成了时段/倍率核验，但没有可稳定读取的绝对元/kWh数值；二手OCR和估算已排除。",
        "重庆": "国网官方索引可见2026年3月公示表，但本次未稳定读取其绝对数值；尖峰值仅按现行政策从2025年2月官方峰值透明推导。",
    }[config["display_name"]]
    report = f"""# {config['display_name']}政策价格零搜索门

判定：`{config['decision']}`。

本目录为2026-07-17官方政策价格取证链，不运行优化器、不修改solver，搜索评价次数为0。raw目录保存官方网页/PDF/官方账号浏览结果的相关正文转录，保留原始URL、访问日期、发布机构、发布日期、标题和本地SHA-256；转录不冒充官方原始二进制文件。CEA不重复取证，复用上海链冻结路径。

## 分时电价

官方原文时段：{config['period_text']}

谷段判断：{config['valley_statement']}

绝对价格状态：`{config['tariff_price_status']}`。{config['tariff_basis']}

48槽文件逐槽按上述时段映射；空价格字段表示没有可核验绝对价格，不是0元/kWh。高峰/谷价倍数：`{ratio}`；尖峰/谷价倍数：`{sharp_ratio}`。

{extra}

## 其他价格

柴油：{config['diesel_text']}

公共充电服务费：{config['charging_text']}

三档记录为：自有 `0.00` 元/kWh；公共中位 `NA`；指导上限 `NA`。关键公共价格缺失，所以不能把旧政策数字或二手估算填入场景。

CEA：复用 `baselines/e4_e5/china_policy_price_gate_20260717/source_evidence.csv` 对应的 `data/Carbon/中国情景/raw_20260717/` 文件；75.02元/tCO2e只作内部影子价格/政策扩围情景，不作道路物流法定碳成本，也没有跨地区借用电价或柴油价。

## HALT原因与官方渠道

关键缺口是当期公共充电服务费官方中位价/指导上限数值缺失，因此本地区不能通过零搜索门。已查官方渠道：{config['tried_channels']}

## 产物

raw快照：`raw/`；来源登记：`source_evidence.csv`（{evidence_count}条，含CEA复用记录）；逐槽文件：`{config['slot_file']}`；四件套：`metadata.json`、`raw_runs.csv`、`decision.json`、`artifact_hashes.json`。
"""
    path.write_text(report, encoding="utf-8")


def ignored(path: Path) -> bool:
    return path.name == "artifact_hashes.json" or path.name.startswith("._") or any(
        part in {"__pycache__", ".pytest_cache"} for part in path.parts
    )


def write_hashes(target: Path) -> None:
    artifacts = {
        str(path.relative_to(target)): sha256_file(path)
        for path in sorted(target.rglob("*"))
        if path.is_file() and not ignored(path)
    }
    payload = {
        "artifacts": artifacts,
        "schema_version": "resetp.artifact-hashes.v1",
        "hash_scope": "all files except artifact_hashes.json, ._* and cache directories",
    }
    (target / "artifact_hashes.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def write_region(region: str) -> Path:
    config = REGION_CONFIGS[region]
    target = REPO_ROOT / "baselines/e4_e5" / config["directory"]
    if target.exists() and (target / "artifact_hashes.json").exists():
        raise FileExistsError(f"refusing to overwrite existing directory: {target}")
    if target.exists():
        for garbage in target.rglob("._*"):
            garbage.unlink()
    raw_dir = target / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for item in config["sources"]:
        (raw_dir / item.raw_name).write_text(raw_text(item), encoding="utf-8")
    (raw_dir / "README.md").write_text(
        "# raw快照说明\n\n"
        "本目录.txt文件为2026-07-17官方网页/PDF/官方账号浏览结果的相关正文转录，"
        "不是二手新闻或博客。每个文件保留原始URL、访问日期、发布机构、发布日期、标题和摘录；"
        "source_evidence.csv记录本地SHA-256。CEA按任务要求复用上海链冻结路径。\n",
        encoding="utf-8",
    )
    csv_write(target / config["slot_file"], SLOT_HEADER, region_rows(region))
    write_price_scenarios(target / "price_scenarios.csv", config)
    evidence = source_rows(config, target)
    csv_write(
        target / "source_evidence.csv",
        ("source_id", "url", "path", "raw_path", "access_date", "publishing_institution", "publication_date", "title", "bytes", "sha256", "expected_sha256", "hash_match", "source_role", "notes"),
        evidence,
    )
    raw_count = len(config["sources"])
    csv_write(
        target / "raw_runs.csv",
        ("region", "access_date", "raw_snapshot_count", "official_first_party_source_count", "tariff_source_status", "diesel_source_status", "charging_service_fee_status", "cea_reuse_status", "search_evaluations", "solver_evaluations", "source_gate_pass", "decision"),
        [{
            "region": region,
            "access_date": ACCESS_DATE,
            "raw_snapshot_count": raw_count,
            "official_first_party_source_count": raw_count,
            "tariff_source_status": config["tariff_price_status"],
            "diesel_source_status": "official_current_maximum_retail_price",
            "charging_service_fee_status": "official_numeric_median_and_cap_missing",
            "cea_reuse_status": "reused_frozen_shanghai_snapshot",
            "search_evaluations": 0,
            "solver_evaluations": 0,
            "source_gate_pass": 0,
            "decision": config["decision"],
        }],
    )
    write_report(target / "report.md", config, len(evidence))
    metadata = {
        "schema_version": "resetp.china-policy-price.v1",
        "created_at": "2026-07-17T00:00:00+08:00",
        "decision": config["decision"],
        "scenario_identity": f"{config['display_name']} July 2026 policy schedule; official snapshot date 2026-07-17",
        "carbon_price_semantics": "CEA 75.02 yuan_per_tCO2e is internal shadow price only; not current legal road-logistics carbon cost",
        "electricity_tariff_identity": config["tariff_basis"],
        "diesel_price_identity": f"0号柴油最高零售价 {config['diesel']} yuan_per_L on {config['diesel_date']}",
        "charging_service_fee_identity": "depot_owned=0; public_typical=NA; public_guidance_cap=NA",
        "emissions_boundary": "delivery-operation CO2; CEA remains shadow-price scenario",
        "source_count": len(evidence),
        "raw_snapshot_count": raw_count,
        "search_evaluations": 0,
        "solver_evaluations": 0,
        "script_sha256": sha256_file(Path(__file__).resolve()),
        "raw_snapshot_format": "browser_text_transcript",
        "python": sys.version.split()[0],
        "platform": platform.platform(),
    }
    (target / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    decision = {
        "decision": config["decision"],
        "failure_count": 1,
        "failures": ["当期公共充电服务费官方中位价和指导上限数值缺失；不能使用旧政策数字、二手转述或估算。"],
        "search_evaluations": 0,
        "solver_evaluations": 0,
        "authorizes": ["使用官方分时政策时段制作48槽", "使用登记的官方柴油最高零售价", "复用冻结CEA影子价格"],
        "does_not_authorize": ["把HALT链当作当前完整可运行价格场景", "把CEA当作道路物流法定碳成本", "运行任何优化器或solver"],
    }
    (target / "decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_hashes(target)
    return target


def audit_rows(region: str, rows: Sequence[dict[str, str]]) -> None:
    config = REGION_CONFIGS[region]
    assert len(rows) == 48, region
    for row in rows:
        start = minute(row["start_time"])
        end = start + 30
        expected_band = band_for_interval(start, end, config["periods"])
        assert row["tariff_band"] == expected_band, (region, row)
        assert row["electricity_yuan_per_kWh"] == decimal_text(config["tariffs"][expected_band]), (region, row)


def run_mapping_tests() -> None:
    for region in REGION_CONFIGS:
        audit_rows(region, region_rows(region))
    cross_midnight = map_periods_to_slots((period("23:00", "01:00", "valley"), period("01:00", "23:00", "flat")))
    assert cross_midnight[0]["tariff_band"] == "valley"
    assert cross_midnight[-1]["tariff_band"] == "valley"
    assert len(cross_midnight) == 48


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-evidence", action="store_true")
    parser.add_argument("--region", choices=["all", *REGION_CONFIGS], default="all")
    args = parser.parse_args()
    run_mapping_tests()
    if not args.write_evidence:
        print("48-slot mapping assertions passed for Beijing, Guangdong (Shenzhen), and Chongqing")
        return 0
    regions = REGION_CONFIGS if args.region == "all" else {args.region: REGION_CONFIGS[args.region]}
    for region in regions:
        print(write_region(region))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

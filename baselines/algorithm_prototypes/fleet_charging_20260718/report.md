# EA-001主题1独立原型功能报告

判决：`PASS_ISOLATED_FUNCTION_PROTOTYPE_ONLY`

治理状态：`EXPLORATION_ONLY_AWAITING_USER_APPROVAL_FOR_FORMAL_USE`

## 做了什么

FC-C02在独立目录中通过可注入适配层调用Apache-2.0 `frvcpy 0.1.1`。人工微例只使用抽象时间和抽象能量：固定客户序列的直达能量不可行，oracle插入一个充电站并给出部分补能量；独立回放不调用frvcpy，逐弧复算能量、分段线性非线性充电时间和总时长。

FC-C05实现了VMR-NL接口桩。候选同时携带客户、路线、插入位置、车辆模式和可选充电请求；筛选优先级、完整评分函数和充电oracle均从外部注入。人工候选中同时包含`CV_DIRECT`、`EV_DIRECT`和`EV_WITH_CHARGE`，用于证明车型—补能联合选择通道能够活跃，不代表正式成本优越。

## 功能结果

预算0/1/2/5均在调用前预留完整评价并严格停在上限。FC-C02四档结果为`['PASS_FUNCTION_ONLY', 'PASS_FUNCTION_ONLY', 'PASS_FUNCTION_ONLY', 'PASS_FUNCTION_ONLY']`；预算2和5出现缓存命中，但完整评价仍分别记2和5，没有因缓存漏账。FC-C05四档结果为`['PASS_FUNCTION_ONLY', 'PASS_FUNCTION_ONLY', 'PASS_FUNCTION_ONLY', 'PASS_FUNCTION_ONLY']`；预算0不筛选、不生成、不评分，预算1只证明单候选通道，预算2起至少两种车辆模式被实际评价，活性门通过。所有有结果的行均由独立直接枚举或SOC回放复算一致。

## 明确保留的接口

原型没有决定人民币车辆固定成本、电价、碳价、正式SOC曲线、初始SOC来源、跨趟SOC继承、充电站容量、排队或接受规则。`score_function`、`FixedRouteChargingRequest.instance`和初始能量都保持可注入；任何正式适配必须另行提交公式、单位、来源和影响分析。

## 不能得出的结论

本探针不能证明FC-C02或FC-C05比当前ALNS更快、更优或更显著，不能证明VMR-NL具有论文新颖性，也不能把抽象微例参数写入中国实例。没有运行正式solver、winner、E7或任何正式E1--E7搜索。

开发首轮单测曾如实暴露两项实现错误：充电曲线递增校验的比较符号写反，以及一个测试调用漏传计数器。两项均在生成本证据包前修复；最终`test_results.txt`记录5项测试全部通过。该修复不改变任何正式模型或参数。

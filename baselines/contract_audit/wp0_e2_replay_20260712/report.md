# E2冻结解参数安全复核

结论：改默认跨场费为0后，3个抽查冻结解仍全部零违规且成本逐位一致。

|算例|算法|seed|冻结成本|当前成本|差值|跨场服务数|违规|结果|
|---|---|---:|---:|---:|---:|---:|---:|---|
|L-main-threeshift-10c-01|staged_hybrid_carbon_aware|1|648.563102875107|648.563102875107|0|0|0|True|
|L-main-threeshift-100c-01|staged_hybrid_carbon_aware|1|5211.846216947982|5211.846216947982|0|0|0|True|
|L-main-threeshift-200c-01|staged_hybrid_carbon_aware|1|9959.411384897756|9959.411384897756|0|0|0|True|

复核按E2封存时的280 kWh内存覆盖和碳价复现；只读加载冻结解并调用当前checker/evaluator，没有重跑搜索，也没有修改E2目录。

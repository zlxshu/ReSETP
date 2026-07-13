# E2—E3 论文预览构建核查

构建日期：2026-07-14。构建只读取封存结果，没有调用路线搜索，也没有改写 E2、E3 证据目录。

## 关键输入指纹

`algorithm_summary.csv`：`e03a14318e354bfbab1ef48f3fff41132429411a06a63af888ea4eeb7e44df33`

`paired_wilcoxon.csv`：`c6e61bd3536d0d0445f968c151c74f5c07990e61cf68e1b1e10f4078153c32a4`

`f2_convergence_curves.csv`：`ecbc0d96abea655c7376504c02155aada958fad4220f3f33933fd11a5fdc7c90`

`portfolio_effect_summary.csv`：`ebb642047f785cf52bb07b4b0d8f1acc5b524ed42e2f4eaf8e0109e5271ce5e6`

代表网络地理聚集责任表：`78e60955353d9bbbf746fd3844a4b8efe8ff566b1748fdd74fdae0e6f96d042a`

代表网络空间交错责任表：`85fc0ecea0cf52193c70864683578c54a2f2b66bc39f0bf3dc9fed924c899509`

## 图件指纹

`e2_convergence.pdf`：`e281400dd96f81c47442c499e5692db3aa916da0d80c8c2e28c9927a509897a9`

`e3_customer_structure.pdf`：`5316c6063ee5962854daf21f8fe5073fc2ce78e4ef74d67eef08de03b7db49ae`

`e3_structure_effect.pdf`：`b1245a62c6262094a2c722f3403ce704065652dbfcb7d1b35c2bc15915f2053a`

## 编译与格式检查

XeLaTeX 连续编译两次通过，正文共 6 页。没有未定义引用、没有版面溢出。PDF 中所有三张统计图均为矢量对象，没有嵌入栅格图片；中文图中文字嵌入 `STSongti-SC-Regular`，英文与数字嵌入 `TimesNewRomanPSMT`。编译器只报告相对路径加载期刊类文件及本机 MiKTeX 更新提示，不影响版面和内容。

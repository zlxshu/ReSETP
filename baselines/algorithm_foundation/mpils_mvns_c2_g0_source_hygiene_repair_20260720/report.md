# MPILS-MVNS-C2 G0 当前源码卫生补正

判定：`FAIL_MPILS_MVNS_C2_G0_SOURCE_HYGIENE_REPAIR`。

G0后Ruff发现`event_driven_ils.py`多导入了未使用的`typing.Any`。当前文件在内存中
补回这一处导入后，SHA-256精确恢复为原G0登记值`8ade27abb8f00f19b4a249df1b34b06abb07590e5f7c19085eb1939656f47c5c`，证明源码只改
这一处无执行用途的导入。

补正后py_compile和Ruff通过；PR11A固定5迭代的上游/迁入母体签名仍相同，人工替换
夹具全部检查仍通过。没有重复5000迭代开销门，没有运行性能题或China81。

当前`event_driven_ils.py` SHA-256为`71590b0f493bdf8e6bc53330b2412a1c4646e98f88d9c40606a09ef59a456b18`。此前G0失败包和两份补正
包均保持不改写；本门是当前源码对应的最终G0状态。

# SCOUT3 三个机制效应探路总报告

终态：`SCOUT3_TERMINAL_WITH_GROUP_HALT`；`formal_result=false`。

## FACT

fleet：`HALT_TECHNICAL`，回答 `None`，最大差 `None`，层 `[]`。

dynamic：`HALT_TECHNICAL`，回答 `None`，最大差 `None`，层 `[]`。

nonlinear：`HALT_TECHNICAL`，回答 `None`，最大差 `None`，层 `[]`。

## DECISION

本包只给用户判断论文保留机制数所需的探路证据；没有代替用户选择机制数，也没有修改论文。

## HALT

技术 HALT 组：`['fleet', 'dynamic', 'nonlinear']`；其余组已继续并保留。因并非三组均形成有/无效应结论，不使用 `SCOUT3_COMPLETE`。

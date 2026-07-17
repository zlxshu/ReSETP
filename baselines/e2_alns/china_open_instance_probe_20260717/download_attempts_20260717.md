# 下载尝试记录（2026-07-17）

## A. 重庆多车场 EVRP-TW 案例

- 论文页面：<https://www.mdpi.com/2071-1050/17/6/2700>
- 页面中的 Data Availability 只写明数据包含在文章内，没有 Zenodo、Mendeley、GitHub 或附件下载地址。
- 结论：没有可直接请求的源数据 URL；不创建伪造的“下载文件”。

## B. JD.com 北京数据 / E-VRP-HC

- 论文正文 PDF：<https://chairelogistique.hec.ca/wp-content/uploads/2025/05/Electric-Vehicle-Routing-with-Heterogeneous-Charging-Stations-1.pdf>
- 论文正文给出的仓库：<https://github.com/wwq-uibe/E-VRP-HC>
- 论文中可核实的是仓库入口和实例命名/规模描述；本轮未能打开仓库树、README、压缩包或原始实例文件。
- 本地 `git ls-remote`/HTTPS 下载受当前环境 DNS 网络限制，无法解析外部代码托管站点；网页工具对 GitHub 直接导航也未获得本轮授权，因而不把“仓库存在”扩大为“文件已下载”。
- 结论：下载未完成；许可、文件名、字段名、坐标系和 SHA-256 均未验证。

## 参考下载尝试（用于判断替代候选，不计为中国候选已下载）

- Zenodo 两层 EVRP：<https://zenodo.org/records/14844216>。页面可读，显示 CC BY 4.0、压缩包和 MD5；本地无法解析 `zenodo.org`，未落盘。
- Zenodo EVRPTW 异质充电站数据：<https://zenodo.org/records/19443014>。论文和页面元数据可读；本地无法解析 `zenodo.org`，未落盘。
- Figshare FEVRPTW：<https://figshare.com/articles/dataset/Fuzzy_optimization_model_for_electric_vehicle_routing_problem_with_time_windows_and_recharging_stations/10288326>。页面给出文件下载入口，但直接 ndownloader 请求在本轮返回 cache miss，未落盘。

## 边界

本目录没有运行优化、没有调用项目算法、没有修改算法代码，也没有把任何论文中的表格手工伪装成数据集文件。


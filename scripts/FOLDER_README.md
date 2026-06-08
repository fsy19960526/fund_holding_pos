<!-- input: D:\freqtrade 模拟盘查询命令、Git 远端与 Windows 任务计划程序。 -->
<!-- output: 每日快照采集脚本与计划任务安装入口。 -->
<!-- pos: scripts 子目录架构索引；一旦我所属的文件夹有所变化，请更新我。 -->

# scripts 架构

本目录只放自动化入口，不承载策略推理逻辑。
采集脚本复用 `D:\freqtrade` 现有 `show_recent_positions.py --save` 输出。
一旦本目录文件增删或职责变化，请同步更新本文档。

| 文件 | 地位 | 功能 |
| --- | --- | --- |
| `capture_position_snapshot.ps1` | 每日采集入口 | 执行仓位查询、保存控制台输出、复制 JSON、提交并推送 Git。 |
| `install_task.ps1` | 计划任务安装入口 | 创建或更新 `FreqtradePositionAudit` 每日 Windows 计划任务。 |

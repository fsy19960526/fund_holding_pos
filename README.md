<!-- input: 仓位审计脚本与 snapshots 目录中的每日快照。 -->
<!-- output: 新仓库使用说明、每日审计文件结构与计划任务入口。 -->
<!-- pos: 仓位持久化审计仓库的根说明；一旦我被更新，务必更新开头注释以及 FOLDER_README.md。 -->

# fund_holding_pos

本仓库用于持久化记录 `D:\freqtrade` 模拟盘的每日仓位变化与近期收益结果。

默认采集命令：

```powershell
D:\freqtrade\.venv\Scripts\python.exe D:\freqtrade\user_func\strategies\research\str_etf_v1\live\show_recent_positions.py --days 8 --save
```

每日快照写入 `snapshots/YYYY-MM-DD/`：

- `show_recent_positions.txt`：原始控制台输出。
- `recent_positions_*.json`：仓位快照。
- `recent_performance_*.json`：组合收益与基准收益。
- `run_meta.json`：采集时间、命令、源文件路径、退出码与 Git 操作结果。

运行一次采集：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File D:\freqtrade_position_audit\scripts\capture_position_snapshot.ps1
```

只做演练、不提交、不推送：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File D:\freqtrade_position_audit\scripts\capture_position_snapshot.ps1 -DryRun
```

安装或更新 Windows 计划任务：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File D:\freqtrade_position_audit\scripts\install_task.ps1
```

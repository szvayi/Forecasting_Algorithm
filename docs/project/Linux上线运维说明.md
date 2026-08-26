# Linux 上线运维说明

目标：先保证 Linux 端可以稳定定期执行，再在稳定运行基础上持续优化算法。

## 1. 涉及的 systemd 单元

- `forecast-dashboard-v2.service`
- `forecast-weekly.service`
- `forecast-weekly.timer`

## 2. 稳定性增强点

- `forecast-dashboard-v2.service`
- 使用 `Restart=on-failure`，避免正常停止后被无限拉起。
- 增加 `StartLimitIntervalSec/StartLimitBurst`，防止异常频繁重启。
- 增加 `TimeoutStartSec/TimeoutStopSec`，避免启动或停止卡死。
- `forecast-weekly.service`
- 增加 `Restart=on-failure` 和 `RestartSec=30`，失败后自动重试。
- 增加 `TimeoutStartSec=2h`，防止任务无限挂起。
- 使用 `flock -n /run/lock/forecast-weekly.lock` 做互斥，防止并发重入。
- `forecast-weekly.timer`
- 固定 `OnCalendar=Mon *-*-* 01:00:00`。
- 增加 `AccuracySec=1min` 和 `RandomizedDelaySec=0`，触发行为更可预期。
- `Persistent=true` 保证主机错过触发后会补跑一次。

## 3. 上线命令清单（可直接执行）

```bash
# 1) 拷贝 unit/timer 到系统目录
sudo cp deploy/systemd/forecast-dashboard-v2.service /etc/systemd/system/
sudo cp deploy/systemd/forecast-weekly.service /etc/systemd/system/
sudo cp deploy/systemd/forecast-weekly.timer /etc/systemd/system/

# 2) 校验 systemd 配置语法
sudo systemd-analyze verify /etc/systemd/system/forecast-dashboard-v2.service
sudo systemd-analyze verify /etc/systemd/system/forecast-weekly.service
sudo systemd-analyze verify /etc/systemd/system/forecast-weekly.timer

# 3) 重新加载并启用服务
sudo systemctl daemon-reload
sudo systemctl enable --now forecast-dashboard-v2.service
sudo systemctl enable --now forecast-weekly.timer

# 4) 查看当前状态
sudo systemctl status forecast-dashboard-v2.service --no-pager
sudo systemctl status forecast-weekly.timer --no-pager
sudo systemctl list-timers forecast-weekly.timer --all --no-pager
```

## 4. 验收命令清单（可执行）

```bash
# A. API 服务是否稳定
sudo systemctl is-active forecast-dashboard-v2.service
sudo journalctl -u forecast-dashboard-v2.service -n 100 --no-pager

# B. 定时器是否启用并有下一次触发
sudo systemctl is-enabled forecast-weekly.timer
sudo systemctl is-active forecast-weekly.timer
sudo systemctl list-timers forecast-weekly.timer --all --no-pager

# C. 手工触发一次周任务
sudo systemctl start forecast-weekly.service
sudo systemctl status forecast-weekly.service --no-pager
sudo journalctl -u forecast-weekly.service -n 100 --no-pager

# D. 互斥验证（第二次触发应被锁拦截）
sudo systemctl start forecast-weekly.service
sudo systemctl start forecast-weekly.service
sudo journalctl -u forecast-weekly.service -n 100 --no-pager
```

说明：互斥验证时，第二次并发启动预期会因 `flock -n` 拿不到锁而失败，这是预期行为。

## 5. 周一 01:00 调度验证步骤（重点）

```bash
# 1) 确认 timer 日历表达式
sudo systemctl cat forecast-weekly.timer

# 2) 查看 Mon 01:00 的下一次触发时间
sudo systemctl list-timers forecast-weekly.timer --all --no-pager

# 3) 辅助校验 calendar 语义
systemd-analyze calendar "Mon *-*-* 01:00:00"

# 4) 到周一 01:00 后，验证是否实际触发过服务
sudo journalctl -u forecast-weekly.timer --since "today 00:50:00" --no-pager
sudo journalctl -u forecast-weekly.service --since "today 00:50:00" --no-pager
```

通过标准：

- `forecast-weekly.timer` 显示 `NEXT` 为最近一个周一 `01:00:00`。
- 周一 `01:00` 后，`forecast-weekly.service` 有新增执行日志。
- 执行失败时可在 `journalctl` 和 `/var/log/forecast-weekly.log` 追踪原因。

## 6. 常用日志命令

```bash
sudo journalctl -u forecast-dashboard-v2.service -f
sudo journalctl -u forecast-weekly.service -f
sudo tail -f /var/log/forecast-dashboard-v2.log
sudo tail -f /var/log/forecast-weekly.log
```

# 环境变量配置（服务器）

本仓库**不再包含**真实数据库账号或密码。部署前必须在服务器上配置环境变量；合并本 PR 前请先配好，否则预测任务会因缺少连接串而失败。

> **安全提醒：** 旧密码曾出现在公开仓库中，合并后请立刻在 PostgreSQL 上**轮换密码**，并只把新密码写进服务器环境 / 密钥管理系统，不要写回代码库。

## 必填

| 变量名 | 说明 | 示例（占位符） |
| --- | --- | --- |
| `SALES_FORECAST_DB_URL` | SQLAlchemy 连接串，预测读写主库 | `postgresql+psycopg2://USER:PASSWORD@HOST:5432/finedatalink` |

推荐使用专用只读 / 读写账号，而不是超级用户。

## 可选 / 别名

| 变量名 | 说明 |
| --- | --- |
| `DATABASE_URL` | 部分 NexusBI / monitor 模块会读；未设 `SALES_FORECAST_DB_URL` 时，`src/config/db.py` 也会回退到它 |
| `SKU_ACCURACY_THRESHOLD` | SKU 过滤阈值，默认 `0.01` |
| `FORECAST_INTERNAL_SCHEDULER_ENABLED` | 设为 `true`/`1` 时启用 API 进程内周调度 |
| `FORECAST_HISTORY_WINDOW_HOURS` | 平台历史窗口小时数，默认 `24` |
| `DEEPSEEK_API_KEY` | 若启用 LLM 相关功能时需要 |
| `SPU_LIST` | 可选，逗号分隔的 SPU 白名单（部分脚本） |

## 服务器如何设置

### Linux（systemd / 登录 shell）

```bash
# 一次性写入当前 shell（调试）
export SALES_FORECAST_DB_URL='postgresql+psycopg2://USER:PASSWORD@HOST:5432/finedatalink'

# 持久化：在服务单元或 /etc/environment / 应用专用 env 文件中写入同一变量
# 例如创建 /etc/forecasting/forecast.env（权限 600，仅运行用户可读）：
#   SALES_FORECAST_DB_URL=postgresql+psycopg2://USER:PASSWORD@HOST:5432/finedatalink
```

systemd 示例：

```ini
[Service]
EnvironmentFile=/etc/forecasting/forecast.env
WorkingDirectory=/opt/Forecasting_Algorithm
ExecStart=/opt/Forecasting_Algorithm/.venv/bin/uvicorn src.api.app:app --host 0.0.0.0 --port 8000
```

### Windows（任务计划 / 服务）

```bat
setx SALES_FORECAST_DB_URL "postgresql+psycopg2://USER:PASSWORD@HOST:5432/finedatalink"
```

或在「系统属性 → 环境变量」中为运行预测的用户添加该变量后重启任务计划。

### 本地开发

```bash
cp .env.example .env
# 编辑 .env 填入真实值；.env 已在 .gitignore 中，勿提交
export $(grep -v '^#' .env | xargs)   # Linux/macOS 简易加载
```

## 代码如何读取

- 统一入口：`src/config/db.py` 中的 `get_sales_forecast_db_url()` / `require_sales_forecast_db_url()`
- 多数脚本与入口使用：`os.getenv("SALES_FORECAST_DB_URL")`（**无明文默认值**）
- 平台 API：`src/api/app.py` 启动时读取该变量并注入 `ForecastRuntimeManager`

## 合并前检查清单

1. 服务器已设置 `SALES_FORECAST_DB_URL`，用只读探测脚本或 `python -c "import os; assert os.getenv('SALES_FORECAST_DB_URL')"` 确认。
2. 轮换数据库密码，撤销曾泄露的旧密码。
3. 合并本 PR 后跑一次周预测 / API 健康检查。
4. Git 历史中仍可能含旧密钥；本 PR **不重写历史**。若仓库保持公开，请务必完成密码轮换，并考虑后续改为私有或做历史清理。

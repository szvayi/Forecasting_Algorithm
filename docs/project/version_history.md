# 版本管理

## 版本历史

| 版本号 | 发布日期 | 主要功能 | 变更说明 |
|--------|----------|----------|----------|
| v8.4 | 2026-03-11 | SPU+SKU 联合可视化版 | 1. 修复了SPU预测结果与SKU份额长度不匹配问题<br>2. 优化了数据库连接管理，用完立即销毁引擎<br>3. 移除了SQL查询中的数据量限制<br>4. 移除了数据库写入时删除旧记录的逻辑<br>5. 支持34个目标SPU的全面测试<br>6. 修复了Prophet模型中外生变量长度不匹配问题<br>7. 增强了日志输出，提供更详细的执行信息 |
| v8.3 | 2026-03-10 | SPU预测引擎 | 1. 实现了多模型预测（Prophet、XGBoost、LightGBM）<br>2. 支持外生变量（广告费用、价格）<br>3. 实现了动态SKU份额计算<br>4. 支持数据库写入功能 |

## 执行记录

| 执行日期 | 执行时间 | 执行命令 | 执行结果 |
|----------|----------|----------|----------|
| 2026-03-11 | 17:02:37 | C:\Users\VY0814\AppData\Local\Programs\Python\Python310\python.exe src\forecasting\main.py | 成功预测34个SPU，写入2960条记录 |
| 2026-03-11 | 16:56:21 | C:\Users\VY0814\AppData\Local\Programs\Python\Python310\python.exe src\forecasting\main.py | 成功预测1个SPU，写入16条记录 |
| 2026-03-11 | 16:16:11 | C:\Users\VY0814\AppData\Local\Programs\Python\Python310\python.exe src\forecasting\main.py | 成功预测1个SPU，写入16条记录 |

## 环境信息

### Python版本
- Python 3.10.11

### 核心依赖包
| 包名 | 版本 | 用途 |
|------|------|------|
| pandas | 2.3.3 | 数据处理 |
| numpy | 2.2.6 | 数值计算 |
| scikit-learn | 1.7.2 | 机器学习 |
| lightgbm | 4.6.0 | 梯度提升模型 |
| xgboost | 3.1.3 | 梯度提升模型 |
| prophet | 1.2.2 | 时间序列预测 |
| pmdarima | 2.1.1 | 时间序列预测 |
| psycopg2 | 2.9.11 | PostgreSQL连接 |
| SQLAlchemy | 2.0.23 | ORM框架 |
| matplotlib | 3.10.8 | 数据可视化 |
| plotly | 6.5.2 | 数据可视化 |
| statsmodels | 0.14.6 | 统计模型 |
| scipy | 1.15.3 | 科学计算 |

### 系统信息
- 操作系统: Windows
- 运行目录: C:\Users\VY0814\Forecasting_Algorithm
- 数据库: PostgreSQL (finedatalink)
- 表名: finedatalink.sales_forecast_history

## 配置信息

### 运行参数
- 运行模式: SMART
- 预测周期: 16周
- 支持的外生变量: ad_cost, price
- 数据查询: 无时间范围限制，自动截取最近156周数据
- 数据库写入: 采用append模式，保留历史数据

### 目标SPU列表
```sql
SELECT '2141' AS SPU UNION ALL 
SELECT '2062' UNION ALL 
SELECT '2029' UNION ALL 
SELECT '2046' UNION ALL 
SELECT '2026' UNION ALL 
SELECT '3022' UNION ALL 
SELECT '1930' UNION ALL 
SELECT '2214' UNION ALL 
SELECT '2033' UNION ALL 
SELECT '2038' UNION ALL 
SELECT '2208' UNION ALL 
SELECT '2012' UNION ALL 
SELECT '3050' UNION ALL 
SELECT '2176' UNION ALL 
SELECT '3033' UNION ALL 
SELECT '2192' UNION ALL 
SELECT '2213' UNION ALL 
SELECT '3063' UNION ALL 
SELECT '2224' UNION ALL 
SELECT '3058' UNION ALL 
SELECT '2073' UNION ALL 
SELECT '3013' UNION ALL 
SELECT '2165' UNION ALL 
SELECT '3084' UNION ALL 
SELECT '1976' UNION ALL 
SELECT '2197' UNION ALL 
SELECT '1476' UNION ALL 
SELECT '1533' UNION ALL 
SELECT '887' UNION ALL 
SELECT '1577' UNION ALL 
SELECT '1750' UNION ALL 
SELECT '1512' UNION ALL 
SELECT '1657' UNION ALL 
SELECT '1983' UNION ALL 
SELECT '1318'
```

## 执行结果

### 数据库状态
- 记录数: 2960
- 成功预测的SPU数量: 34
- 每个SPU预测周数: 16

### 报告文件
- 回测报告: spu_backtest_report_20260311_171423.html
- 摘要报告: C:\Users\VY0814\Desktop\spu_forecast_summary_report.html

## 注意事项

1. 数据不再被删除，可通过run_date字段查询不同时间的预测结果
2. 系统会自动处理数据量不足的情况，有多少数据用多少数据
3. 预测结果已包含SKU级别的动态份额计算
4. 所有模型训练和预测过程均已记录在日志文件中

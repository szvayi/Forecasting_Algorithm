# SPU预测分析系统

## 系统架构

### 前端
- `forecast_dashboard.html` - 预测分析仪表板，用于启动分析、显示进度和结果
- `index.html` - 详细报告页面

### 报告输出
- `reports/` - 已生成报告与历史报告归档
- `reports/generated/` - 分析辅助脚本生成的 HTML 输出

### 后端
- `src/api/app.py` - FastAPI应用，提供API端点
- `src/api/analysis_worker.py` - 分析工作脚本，执行实际的预测分析
- `main.py` - 核心预测逻辑，包含数据获取、模型训练和预测功能
- `config_and_utils.py` - 配置和工具函数
- `algorithm_engine.py` - 算法引擎，包含各种预测模型

## 工作流程

1. **前端启动分析**：用户在 `forecast_dashboard.html` 页面点击"开始预测分析"按钮
2. **API请求**：前端向 `http://localhost:8000/api/start-analysis` 发送POST请求
3. **后台任务**：FastAPI应用启动一个后台任务，调用 `analysis_worker.py` 脚本
4. **执行预测**：`analysis_worker.py` 从根目录下的 `main.py` 导入函数，执行预测分析
5. **进度更新**：`analysis_worker.py` 实时输出进度信息，API服务将其传递给前端
6. **结果展示**：分析完成后，前端显示预测结果和统计信息

## 关键配置

- **API服务**：运行在 `http://localhost:8000`
- **数据库URL**：从环境变量 `SALES_FORECAST_DB_URL` 获取，默认值为 `postgresql+psycopg2://postgres:vayiERty123@192.168.1.226:5432/finedatalink`
- **SPU评估阈值**：从环境变量 `SKU_ACCURACY_THRESHOLD` 获取，默认值为 0.01

## 如何运行

1. **启动API服务**：
   ```bash
   uvicorn src.api.app:app --host 0.0.0.0 --port 8000
   ```

2. **打开前端页面**：
   - 浏览器访问 `forecast_dashboard.html`
   - 点击"开始预测分析"按钮启动分析

3. **查看结果**：
   - 分析完成后，前端会显示预测结果和统计信息
   - 点击"查看详细报告"按钮查看详细报告

## 注意事项

- 预测分析可能需要较长时间，具体取决于数据量和系统性能
- 分析过程中，前端会实时显示进度信息
- 分析结果会保存到数据库中，表名为 `finedatalink.sales_forecast_history`
- 如果分析失败，前端会显示错误信息

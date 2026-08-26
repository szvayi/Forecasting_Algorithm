# 销售预测系统需求文档

## 1. 项目概述 (Project Overview)
本项目旨在建立一个自动化的销售预测系统，能够对 SPU（Standard Product Unit） 和 SKU（Stock Keeping Unit） 两个层级进行销量预测。系统整合了多种预测模型，通过历史数据进行训练、验证和未来预测，并支持将预测结果（包括 SPU 预测、SKU 预测拆分、季节因子等）持久化存储到数据库。同时，系统提供直观的数据可视化功能，以便用户快速理解预测结果和模型表现。

## 2. 核心功能 (Core Functionalities)

### 2.1 SPU 销量预测 (SPU Sales Forecasting)
- **多模型预测**: 系统支持多种预测模型，例如 Prophet, Ensemble_Seas, Ensemble_Wgt, Ensemble_Trend 等，对 SPU 的历史周销量数据进行分析和预测。
- **模型评估**: 使用 WMAPE (Weighted Mean Absolute Percentage Error) 作为主要评估指标，对不同模型的预测性能进行量化评估。
- **最佳模型选择**: 自动识别并选择在验证集上表现最佳（WMAPE 最低）的模型作为当前 SPU 的“胜出模型 (Winner Model)”，并用其生成最终的未来 SPU 预测。
- **未来预测**: 生成指定未来时间范围（例如未来 X 周）的 SPU 销量预测值。

### 2.2 SKU 销量预测 (SKU Sales Forecasting)
- **SPU-SKU 联动**: SKU 的销量预测是基于 SPU 的预测结果和 SKU 在历史销售中的动态占比（Share）计算得出。
- **动态占比计算**: 系统能够根据历史数据计算每个 SKU 在其所属 SPU 总销量中的动态百分比份额。
- **预测公式**: SKU_未来预测量 = SPU_未来预测量 × SKU_动态占比 。
- **细粒度预测**: 实现对 SPU 下多个 SKU 的独立预测，并能将其结果以 JSON 格式存储。

### 2.3 季节因子提取 (Seasonal Factor Extraction)
- **52 周季节因子**: 系统能够从 SPU 的历史周销量数据中提取一个完整周期（52 周）的季节因子。
- **输出格式**: 季节因子以 JSON 格式存储，Key 为 week_1 到 week_52 ，Value 为对应的季节因子数值。例如： {"week_1": 0.85, "week_2": 0.92, ..., "week_52": 1.10} 。
- **因子处理**: 提取的季节因子会经过平滑处理，并限制在合理范围（例如 0.5 到 1.5 之间），确保因子稳定性。如果历史数据不足，将返回均匀因子（1.0）。

### 2.4 数据可视化 (Data Visualization)
- **综合预测图表**: 生成一张包含 SPU 和 SKU 预测的综合图表，内容包括：
    - **历史数据**: SPU 的历史周销量（灰色线条）。
    - **实际值**: 验证期内的实际销量（黑色线条，点标记）。
    - **模型预测**: 多个模型的预测线条（不同颜色和标记）在验证期内进行展示。
    - **SPU 未来预测**: 胜出模型生成的 SPU 未来预测曲线（粗紫色线条，菱形标记）。
    - **SKU 未来预测**: 胜出模型下的 销量排名靠前（例如 Top 5）的 SKU 预测曲线 ，以虚线（不同颜色，圆点标记）形式展示在预测区间，直观展现 SPU 预测的 SKU 构成。
    - **区间标记**: 验证区间（黄色阴影）和预测区间（绿色阴影）高亮显示。
    - **标题**: 包含 SPU ID、预测主题、胜出模型名称及其 WMAPE。
- **模型 WMAPE 对比**: 一个独立的柱状图，展示参与预测的各个模型在验证期内的 WMAPE，用于横向比较模型性能。胜出模型的柱子会进行高亮显示。
- **字体支持**: 图表支持使用自定义字体文件 ( sider-font.ttf )，确保显示效果符合要求。

### 2.5 数据存储与管理 (Data Storage & Management)
- **数据库**: 将预测结果存储到 PostgreSQL 数据库的 finedatalink.sales_forecast_history 表中。
- **存储内容**: 包含但不限于：SPU ID, 运行日期, 预测目标日期, SPU 预测值, SKU 份额 JSON ( sku_share_json ), 季节因子 JSON ( seasonal_factors_json ), SKU 误差评估 JSON ( sku_accuracy_json ), 胜出模型名称, 验证期 WMAPE, 最佳模型参数 JSON, 是否使用外部特征, 使用的外部特征列名, 训练周数, 数据结束日期。
- **JSON 字段**: sku_share_json、seasonal_factors_json、sku_accuracy_json 字段用于存储结构化数据。其中 sku_accuracy_json 用于记录“SPU×份额”方式在验证期内各 SKU 的误差（WMAPE）及权重信息，支持 SPU 与其下 SKU 的误差对比分析。

## 3. 技术细节 (Technical Details)

### 3.1 数据输入 (Data Input)
- **历史销售数据**: 主要输入为周粒度的 SPU 销量数据，以及 SPU 下各 SKU 的周销量数据。
- **外部特征 (Exogenous Features)**: 系统支持引入外部特征（如节假日、促销活动等）来增强预测模型的准确性。

### 3.2 数据处理流程 (Data Processing Flow)
核心处理逻辑集中在 main.py 的 process_single_spu 函数中，主要算法逻辑由 **algorithm_engine.py** 提供，并通过 config_and_utils.py 提供的工具函数完成。主要步骤包括：
- **数据清洗与准备**: 对原始销量数据进行预处理，包括缺失值处理、异常值检测等。
- **模型训练与验证**:
    - 将历史数据拆分为训练集和验证集。
    - 对每个模型在训练集上进行训练，并在验证集上进行预测和 WMAPE 评估。
- **胜出模型确定**: 根据验证集 WMAPE 选出最佳模型。
- **SPU 未来预测**: 使用胜出模型生成未来的 SPU 预测。
- **SKU 动态份额计算**: 调用 calculate_dynamic_shares 函数，根据 SPU 和 SKU 历史数据计算 SKU 占比，输出 JSON 格式和 DataFrame 格式。
- **季节因子提取**: 调用 extract_seasonal_factors_52week 函数，从清洗后的 SPU 历史数据中提取 52 周季节因子，并格式化为 JSON 字符串。
- **结果整合**: 将 SPU 预测、SKU 份额 JSON、季节因子 JSON、模型评估指标、最佳参数等信息整合到一个 DataFrame ( result_df ) 中。
- **图表生成**: 调用 plot_best_spu_style 函数生成预测可视化图表，并支持保存到指定路径。
- **数据持久化**: 调用 save_to_database 函数将 result_df 写入 PostgreSQL 数据库。

### 3.3 模型选择与评估 (Model Selection & Evaluation)
- **模型列表**: 具体使用的模型包括 Prophet、以及不同的 Ensemble 组合（例如 Ensemble_Seas、Ensemble_Wgt、Ensemble_Trend）。
- **评估指标**: WMAPE。
- **参数优化**: 模型可能进行内部参数搜索或调整以优化性能。

### 3.4 数据库交互 (Database Interaction)
- **数据库类型**: PostgreSQL。
- **表名**: finedatalink.sales_forecast_history 。
- **新增字段**:
    - seasonal_factors_json : JSON 类型，存储 52 周季节因子。
    - sku_accuracy_json : JSON 类型（或 TEXT），存储验证期内各 SKU 误差评估结果（WMAPE、权重等）。
- **现有 JSON 字段**:
    - sku_share_json : JSON 类型，存储 SKU 动态占比信息。
- **ORM/库**: 使用 pandas.to_sql 进行数据写入，简化了数据库操作。
- **连接管理**: 确保数据库连接的正确打开和关闭/释放。
- **参数序列化**: 对存储到数据库的复杂对象（如模型参数）进行安全的 JSON 序列化处理，防止写入失败。

### 3.5 图表输出 (Chart Output)
- **绘图库**: matplotlib 。
- **输出格式**: 支持图片文件（如 PNG）和直接在界面显示。
- **自定义字体**: 通过 matplotlib.font_manager 加载并应用 sider-font.ttf 字体。

### 3.6 关键模块/文件 (Key Modules/Files)
- **main.py**: 项目入口和主流程控制，包括数据加载、SPU 循环、 process_single_spu 的调用。
- **algorithm_engine.py**: 核心算法引擎，包含各种预测模型的实现（Prophet, Ensemble等）以及模型训练、预测的主要逻辑。
- **config_and_utils.py**: 包含所有共享工具函数、配置、数据预处理、动态份额计算 ( calculate_dynamic_shares )、季节因子提取 ( extract_seasonal_factors_52week )、绘图逻辑 ( plot_best_spu_style )、数据库操作 ( save_to_database ) 等。这是业务辅助逻辑和通用功能的封装地。
- **sider-font.ttf**: 自定义字体文件，用于图表的文本显示。

## 4. 已实现及修复点 (Implemented Features & Fixes)
- ✅ **SKU 预测图表整合**: 在 SPU 预测主图上，成功叠加了 Top N SKU 的预测曲线，并显示了验证/预测区间及模型对比。
- ✅ **52 周季节因子提取**: 新增了 extract_seasonal_factors_52week 函数，实现了季节因子提取并存储为 JSON 格式。
- ✅ **数据库字段扩展**: 已向 sales_forecast_history 表添加 seasonal_factors_json 字段。
- ✅ **代码语法修复**: 修复了 config_and_utils.py 中因意外字符导致的 SyntaxError 。
- ✅ **中文字体支持**: 确保图表正确显示中文字符，避免乱码。
- ✅ **参数安全序列化**: 优化了复杂参数（如 best_params ）的 JSON 序列化，确保能顺利存入数据库。
- ✅ **数据库连接管理**: 确保数据库连接的创建和关闭/释放逻辑健壮。
- ✅ **批量处理与并行化**: 优化了 SPU 预测的批量处理流程，在 main.py 中引入了 concurrent.futures.ProcessPoolExecutor 实现多进程并行计算，大幅缩短了整体运行时间。
- ✅ **SPU vs SKU 误差对比**: 新增 sku_accuracy_json，用于评估“SPU×动态份额”拆分方式在验证期内各 SKU 的误差率（WMAPE），支持按从属关系对比分析。
- ✅ **SKU 过滤阈值可配置**: 支持通过环境变量 `SKU_ACCURACY_THRESHOLD` 配置长尾 SKU 过滤阈值（默认 1%）。
- ✅ **数据库视图**: 创建了视图 `v_spu_sku_accuracy_detail`，直接输出 SPU 与 SKU 的误差对比明细。

## 5. 待优化/未来迭代 (Future Enhancements/Iterations)
- **可视化参数可配置**: 将 plot_best_spu_style 中的 Top N SKU 数量、颜色方案、堆叠图是否显示等参数暴露为可配置项，提高灵活性。
- **交互式图表**: 考虑引入 Plotly 或 Bokeh 等库，生成交互式的预测图表，提供更丰富的用户体验（如悬停显示数据点信息）。
- **SKU 份额预测**: 目前 SKU 份额是基于历史平均/动态计算，未来可考虑使用更复杂的模型（如机器学习）来预测 SKU 的未来份额。
- **预测准确性监控与反馈**: 建立预测准确性的长期监控机制，并结合实际销售数据进行定期回溯分析和模型调优。
- **日志记录与告警**: 增加详细的运行日志和关键异常告警机制，便于问题排查和系统稳定性维护。
- **单元测试与集成测试**: 为核心函数和模块编写单元测试，为整个预测流程编写集成测试，提升代码质量和系统稳定性。

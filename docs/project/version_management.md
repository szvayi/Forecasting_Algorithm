# 版本管理方案

## 1. 概述

本文档详细说明SPU预测分析报告的版本管理方案，确保前端能够有效地管理和追踪报告的不同版本，同时保证数据的一致性和可追溯性。

## 2. 版本管理策略

### 2.1 文件名版本控制

- **命名格式**：使用 `final_spu_analysis_report_{version}.html` 格式命名文件
- **版本号生成**：
  - 基于时间戳：`v{timestamp}`，如 `v1704067200000`
  - 基于递增数字：`v{number}`，如 `v1.0`, `v1.1`
- **存储位置**：
  - 前端本地存储：使用 `localStorage` 存储报告和数据
  - 服务器存储（可选）：`/Forecasting_Algorithm/reports/` 目录

### 2.2 文件内版本信息

- **HTML报告**：在报告HTML中添加版本标识和生成时间
  - 版本号：在报告头部显示
  - 生成时间：在报告页脚显示
  - 分析ID：唯一标识符，用于追踪分析过程

- **数据文件**：在JSON数据文件中包含版本信息
  ```json
  {
    "metadata": {
      "version": "v1.0",
      "analysis_id": "anal_1704067200000",
      "timestamp": "2024-01-01T00:00:00Z",
      "prediction_id": "pred_12345"
    },
    "data": { ... }
  }
  ```

### 2.3 版本变更记录

- **版本历史文件**：创建 `version_history.json` 文件，记录各版本的变更内容
  ```json
  [
    {
      "version": "v1.1",
      "timestamp": "2024-01-02T00:00:00Z",
      "analysis_id": "anal_1704153600000",
      "prediction_id": "pred_12346",
      "changes": ["修复趋势计算逻辑", "优化报告样式"],
      "total_spus": 35
    },
    {
      "version": "v1.0",
      "timestamp": "2024-01-01T00:00:00Z",
      "analysis_id": "anal_1704067200000",
      "prediction_id": "pred_12345",
      "changes": ["初始版本", "实现基本分析功能"],
      "total_spus": 32
    }
  ]
  ```

- **前端版本管理界面**：提供版本历史查看和版本切换功能

### 2.4 数据文件分离

- **数据存储**：
  - JSON格式数据文件：`spu_forecast_data_{version}.json`
  - 包含所有分析数据，方便前端直接处理
  - 与HTML报告分离，便于数据复用

- **数据结构**：
  ```json
  {
    "metadata": {
      "version": "v1.0",
      "analysis_id": "anal_1704067200000",
      "timestamp": "2024-01-01T00:00:00Z",
      "prediction_id": "pred_12345",
      "total_spus": 32,
      "average_wmape": 0.085
    },
    "spu_analyses": [
      {
        "spu_id": "0887",
        "name": "示例SPU",
        "metrics": {
          "average_wmape": 0.0983,
          "total_records": 14,
          "performance_rating": "良好",
          "model": "Ensemble_Stack"
        },
        "trends": {
          "four_week_trend": {
            "start_date": "2026-03-05",
            "end_date": "2026-04-02",
            "start_value": 100,
            "end_value": 155.76,
            "change_percentage": 0.5576,
            "direction": "增长"
          },
          "eight_week_trend": {
            "start_date": "2026-03-05",
            "end_date": "2026-04-30",
            "start_value": 100,
            "end_value": 234.53,
            "change_percentage": 1.3453,
            "direction": "增长"
          }
        }
      }
    ],
    "overall_trends": {
      "four_week_average_change": 0.45,
      "eight_week_average_change": 0.85,
      "top_performing_spus": ["0887", "0921", "0756"],
      "bottom_performing_spus": ["0642", "0531", "0429"]
    }
  }
  ```

## 3. 前端版本管理实现

### 3.1 本地存储策略

- **localStorage**：用于存储报告和数据
  - 存储键格式：`final_spu_analysis_report_{version}` 和 `spu_forecast_data_{version}`
  - 版本历史：`version_history`
  - 存储限制：注意localStorage的5MB限制，建议只保留最近10个版本

- **IndexedDB**（可选）：用于存储大量历史数据
  - 适合存储完整的历史报告和数据
  - 支持更复杂的查询和索引

### 3.2 版本管理函数

```javascript
/**
 * 保存分析结果和报告
 * @param {Object} analysisResults - 分析结果
 * @param {string} htmlReport - HTML报告
 * @returns {string} 版本号
 */
function saveReport(analysisResults, htmlReport) {
  // 生成版本号
  const version = `v${Date.now()}`;
  
  // 保存分析结果为JSON
  const jsonData = JSON.stringify(analysisResults, null, 2);
  localStorage.setItem(`spu_forecast_data_${version}`, jsonData);
  
  // 保存HTML报告
  localStorage.setItem(`final_spu_analysis_report_${version}`, htmlReport);
  
  // 更新版本历史
  const versionHistory = JSON.parse(localStorage.getItem('version_history') || '[]');
  versionHistory.unshift({
    version: version,
    timestamp: new Date().toISOString(),
    analysis_id: analysisResults.metadata.analysis_id,
    prediction_id: analysisResults.metadata.prediction_id,
    total_spus: analysisResults.metadata.total_spus
  });
  
  // 只保留最近10个版本
  const trimmedHistory = versionHistory.slice(0, 10);
  localStorage.setItem('version_history', JSON.stringify(trimmedHistory));
  
  return version;
}

/**
 * 获取版本历史
 * @returns {Array} 版本历史
 */
function getVersionHistory() {
  return JSON.parse(localStorage.getItem('version_history') || '[]');
}

/**
 * 获取指定版本的报告
 * @param {string} version - 版本号
 * @returns {Object} 报告和数据
 */
function getReportByVersion(version) {
  const htmlReport = localStorage.getItem(`final_spu_analysis_report_${version}`);
  const jsonData = localStorage.getItem(`spu_forecast_data_${version}`);
  
  return {
    html: htmlReport,
    data: jsonData ? JSON.parse(jsonData) : null
  };
}
```

### 3.3 版本切换功能

- **前端界面**：提供版本选择下拉菜单
- **切换逻辑**：
  1. 从版本历史中获取所有版本
  2. 用户选择版本后，加载对应版本的报告和数据
  3. 显示所选版本的分析结果

### 3.4 自动版本管理

- **版本检测**：当预测数据更新时，自动生成新版本报告
- **版本比较**：比较当前版本与历史版本的差异
- **版本归档**：自动归档旧版本，保留最新版本

## 4. 服务器端版本管理（可选）

### 4.1 文件存储

- **目录结构**：
  ```
  /Forecasting_Algorithm/
    /reports/
      final_spu_analysis_report_v1.0.html
      final_spu_analysis_report_v1.1.html
    /data/
      spu_forecast_data_v1.0.json
      spu_forecast_data_v1.1.json
    version_history.json
  ```

### 4.2 API接口

- **获取版本历史**：`GET /api/reports/versions`
- **获取指定版本**：`GET /api/reports/{version}`
- **创建新版本**：`POST /api/reports`
- **删除版本**：`DELETE /api/reports/{version}`

## 5. 最佳实践

### 5.1 版本管理建议

1. **定期清理**：定期清理过期版本，避免存储空间不足
2. **版本命名**：使用有意义的版本号，如基于日期或功能变更
3. **变更记录**：详细记录每个版本的变更内容，便于追溯
4. **数据备份**：定期备份版本历史和分析数据

### 5.2 性能优化

1. **增量更新**：只更新变化的数据，减少存储和传输开销
2. **数据压缩**：对JSON数据进行压缩，减少存储空间
3. **缓存策略**：合理使用浏览器缓存，提高加载速度

### 5.3 安全性

1. **数据验证**：验证输入数据的完整性和正确性
2. **访问控制**：限制对版本历史的访问权限
3. **数据加密**：对敏感数据进行加密存储

## 6. 实施计划

### 6.1 阶段一：基础实现

1. 实现前端本地存储版本管理
2. 创建版本历史记录功能
3. 实现版本切换界面

### 6.2 阶段二：高级功能

1. 实现服务器端版本存储
2. 开发API接口
3. 集成版本比较功能

### 6.3 阶段三：优化和扩展

1. 实现数据压缩和增量更新
2. 开发版本管理仪表盘
3. 集成自动化版本生成

## 7. 总结

通过实施本版本管理方案，前端可以：

1. **追踪历史版本**：记录和管理所有分析报告版本
2. **保证数据一致性**：确保分析数据的可追溯性
3. **提高用户体验**：提供版本切换和历史查看功能
4. **优化存储效率**：合理管理存储空间，避免数据冗余

本方案为前端集成分析报告生成功能提供了完整的版本管理框架，确保分析结果的可靠性和可追踪性。
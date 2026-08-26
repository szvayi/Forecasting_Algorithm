# 前端数据流动方案设计

## 1. 方案概述

本方案旨在设计前端数据流动流程，确保预测数据能够直接用于分析，实现从预测数据到分析报告的端到端流程。通过合理的数据结构设计和处理流程，确保数据的一致性、完整性和实时性。

## 2. 数据结构设计

### 2.1 预测数据结构

```javascript
// 预测数据结构
const predictionData = {
  metadata: {
    prediction_id: "pred_20260312_001", // 预测任务ID
    timestamp: "2026-03-12T10:00:00Z", // 预测时间
    model_version: "v1.2.0", // 模型版本
    data_source: "realtime", // 数据来源
    total_spus: 35, // SPU总数
    total_records: 560 // 总记录数
  },
  spus: [
    {
      spu_id: "0887", // SPU编号
      name: "产品A", // 产品名称（可选）
      records: [
        {
          date: "2026-03-05", // 日期
          actual_value: 100, // 实际值
          forecast_value: 105, // 预测值
          wmape: 0.05, // 加权平均绝对百分比误差
          model: "Ensemble_Stack" // 使用的模型
        },
        {
          date: "2026-03-12",
          actual_value: 110,
          forecast_value: 112,
          wmape: 0.018,
          model: "Ensemble_Stack"
        },
        {
          date: "2026-03-19",
          actual_value: null, // 未来日期无实际值
          forecast_value: 118,
          wmape: null,
          model: "Ensemble_Stack"
        },
        {
          date: "2026-03-26",
          actual_value: null,
          forecast_value: 125,
          wmape: null,
          model: "Ensemble_Stack"
        },
        {
          date: "2026-04-02",
          actual_value: null,
          forecast_value: 130,
          wmape: null,
          model: "Ensemble_Stack"
        },
        {
          date: "2026-04-09",
          actual_value: null,
          forecast_value: 135,
          wmape: null,
          model: "Ensemble_Stack"
        },
        {
          date: "2026-04-16",
          actual_value: null,
          forecast_value: 132,
          wmape: null,
          model: "Ensemble_Stack"
        },
        {
          date: "2026-04-23",
          actual_value: null,
          forecast_value: 130,
          wmape: null,
          model: "Ensemble_Stack"
        },
        {
          date: "2026-04-30",
          actual_value: null,
          forecast_value: 128,
          wmape: null,
          model: "Ensemble_Stack"
        },
        {
          date: "2026-05-07",
          actual_value: null,
          forecast_value: 125,
          wmape: null,
          model: "Ensemble_Stack"
        }
      ]
    },
    // 其他SPU数据...
  ]
};
```

### 2.2 分析结果数据结构

```javascript
// 分析结果数据结构
const analysisResults = {
  metadata: {
    analysis_id: "anal_20260312_001", // 分析任务ID
    timestamp: "2026-03-12T10:30:00Z", // 分析时间
    prediction_id: "pred_20260312_001", // 关联的预测任务ID
    version: "v1.0", // 分析版本
    total_spus: 35, // 分析的SPU总数
    average_wmape: 0.0983 // 整体平均WMAPE
  },
  spu_analyses: [
    {
      spu_id: "0887",
      name: "产品A",
      metrics: {
        average_wmape: 0.0983, // 平均WMAPE
        total_records: 18, // 记录数
        performance_rating: "良好", // 性能评价
        model: "Ensemble_Stack" // 使用的模型
      },
      trends: {
        four_week_trend: {
          start_date: "2026-03-05",
          end_date: "2026-04-02",
          start_value: 105,
          end_value: 130,
          change_percentage: 0.2381, // 23.81%
          direction: "增长"
        },
        eight_week_trend: {
          start_date: "2026-03-05",
          end_date: "2026-04-30",
          start_value: 105,
          end_value: 128,
          change_percentage: 0.2190, // 21.90%
          direction: "增长"
        }
      }
    },
    // 其他SPU分析结果...
  ],
  overall_trends: {
    four_week_average_change: 0.25, // 4周平均变化率
    eight_week_average_change: 0.20, // 8周平均变化率
    top_performing_spus: ["1812", "3062", "3068"], // 表现最好的SPU
    bottom_performing_spus: ["0887", "3071", "3079"] // 表现最差的SPU
  }
};
```

## 3. 数据流动流程

### 3.1 数据流图

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│ 预测数据API     │ ──> │ 数据获取模块     │ ──> │ 数据处理模块     │ ──> │ 分析计算模块     │
└─────────────────┘     └─────────────────┘     └─────────────────┘     └─────────────────┘
                                                                 │
                                                                 ▼
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│ 版本管理模块     │ <── │ 报告生成模块     │ <── │ 前端渲染模块     │ <── │ 数据存储模块     │
└─────────────────┘     └─────────────────┘     └─────────────────┘     └─────────────────┘
```

### 3.2 详细流程

1. **数据获取**
   - 从预测API获取原始预测数据
   - 验证数据完整性和格式
   - 存储到前端临时存储（localStorage）

2. **数据处理**
   - 数据清洗：处理缺失值、异常值
   - 数据转换：统一日期格式、数值格式
   - 数据分组：按SPU、日期等维度分组

3. **分析计算**
   - 计算每个SPU的平均WMAPE
   - 计算4周和8周的趋势
   - 生成性能评价
   - 计算整体趋势和统计指标

4. **数据存储**
   - 存储分析结果到localStorage
   - 生成JSON格式的数据文件
   - 维护版本历史记录

5. **前端渲染**
   - 基于分析结果渲染报告页面
   - 生成HTML格式的报告
   - 提供报告预览和下载功能

6. **版本管理**
   - 生成版本号
   - 记录版本变更历史
   - 管理报告和数据文件的版本

## 4. 数据处理函数设计

### 4.1 数据获取函数

```javascript
/**
 * 获取预测数据
 * @param {string} predictionId - 预测任务ID
 * @returns {Promise<Object>} 预测数据
 */
async function fetchPredictionData(predictionId) {
  try {
    // 先检查本地缓存
    const cachedData = localStorage.getItem(`prediction_${predictionId}`);
    if (cachedData) {
      return JSON.parse(cachedData);
    }
    
    // 从API获取数据
    const response = await fetch(`/api/predictions/${predictionId}`);
    if (!response.ok) {
      throw new Error('Failed to fetch prediction data');
    }
    
    const data = await response.json();
    
    // 缓存数据
    localStorage.setItem(`prediction_${predictionId}`, JSON.stringify(data));
    
    return data;
  } catch (error) {
    console.error('Error fetching prediction data:', error);
    throw error;
  }
}
```

### 4.2 数据处理函数

```javascript
/**
 * 处理预测数据
 * @param {Object} predictionData - 原始预测数据
 * @returns {Object} 处理后的数据
 */
function processData(predictionData) {
  // 检查数据完整性
  if (!predictionData || !predictionData.spus) {
    throw new Error('Invalid prediction data format');
  }
  
  // 处理每个SPU的数据
  const processedSpus = predictionData.spus.map(spu => {
    // 确保记录按日期排序
    const sortedRecords = [...spu.records].sort((a, b) => {
      return new Date(a.date) - new Date(b.date);
    });
    
    // 计算平均WMAPE（只考虑有实际值的记录）
    const actualRecords = sortedRecords.filter(record => record.actual_value !== null);
    const totalWeight = actualRecords.reduce((sum, record) => sum + record.actual_value, 0);
    const weightedErrors = actualRecords.reduce((sum, record) => {
      const error = Math.abs(record.actual_value - record.forecast_value);
      return sum + (error / record.actual_value) * record.actual_value;
    }, 0);
    
    const averageWmape = totalWeight > 0 ? weightedErrors / totalWeight : null;
    
    return {
      ...spu,
      records: sortedRecords,
      average_wmape: averageWmape,
      performance_rating: getPerformanceRating(averageWmape)
    };
  });
  
  return {
    ...predictionData,
    spus: processedSpus
  };
}

/**
 * 获取性能评价
 * @param {number} wmape - 加权平均绝对百分比误差
 * @returns {string} 性能评价
 */
function getPerformanceRating(wmape) {
  if (wmape === null) return "未知";
  if (wmape < 0.05) return "优秀";
  if (wmape < 0.10) return "良好";
  if (wmape < 0.15) return "一般";
  return "较差";
}
```

### 4.3 趋势计算函数

```javascript
/**
 * 计算趋势
 * @param {Array} records - SPU记录
 * @returns {Object} 趋势分析结果
 */
function calculateTrends(records) {
  // 按日期排序
  const sortedRecords = [...records].sort((a, b) => {
    return new Date(a.date) - new Date(b.date);
  });
  
  // 查找指定日期的预测值
  const getForecastValueByDate = (date) => {
    const record = sortedRecords.find(r => r.date === date);
    return record ? record.forecast_value : null;
  };
  
  // 4周趋势：2026-04-02 / 2026-03-05
  const startDate4w = "2026-03-05";
  const endDate4w = "2026-04-02";
  const startValue4w = getForecastValueByDate(startDate4w);
  const endValue4w = getForecastValueByDate(endDate4w);
  
  // 8周趋势：2026-04-30 / 2026-03-05
  const startDate8w = "2026-03-05";
  const endDate8w = "2026-04-30";
  const startValue8w = getForecastValueByDate(startDate8w);
  const endValue8w = getForecastValueByDate(endDate8w);
  
  // 计算变化率
  const calculateChangePercentage = (start, end) => {
    if (start === null || end === null || start === 0) return null;
    return (end - start) / start;
  };
  
  const fourWeekChange = calculateChangePercentage(startValue4w, endValue4w);
  const eightWeekChange = calculateChangePercentage(startValue8w, endValue8w);
  
  return {
    four_week_trend: {
      start_date: startDate4w,
      end_date: endDate4w,
      start_value: startValue4w,
      end_value: endValue4w,
      change_percentage: fourWeekChange,
      direction: fourWeekChange > 0 ? "增长" : fourWeekChange < 0 ? "下降" : "稳定"
    },
    eight_week_trend: {
      start_date: startDate8w,
      end_date: endDate8w,
      start_value: startValue8w,
      end_value: endValue8w,
      change_percentage: eightWeekChange,
      direction: eightWeekChange > 0 ? "增长" : eightWeekChange < 0 ? "下降" : "稳定"
    }
  };
}
```

### 4.4 分析计算函数

```javascript
/**
 * 分析预测数据
 * @param {Object} processedData - 处理后的数据
 * @returns {Object} 分析结果
 */
function analyzeData(processedData) {
  const spuAnalyses = processedData.spus.map(spu => {
    const trends = calculateTrends(spu.records);
    
    return {
      spu_id: spu.spu_id,
      name: spu.name,
      metrics: {
        average_wmape: spu.average_wmape,
        total_records: spu.records.length,
        performance_rating: spu.performance_rating,
        model: spu.records[0]?.model || "未知"
      },
      trends: trends
    };
  });
  
  // 计算整体指标
  const validSpus = spuAnalyses.filter(spu => spu.metrics.average_wmape !== null);
  const averageWmape = validSpus.length > 0 
    ? validSpus.reduce((sum, spu) => sum + spu.metrics.average_wmape, 0) / validSpus.length
    : null;
  
  // 计算平均变化率
  const fourWeekChanges = spuAnalyses
    .map(spu => spu.trends.four_week_trend.change_percentage)
    .filter(change => change !== null);
  const eightWeekChanges = spuAnalyses
    .map(spu => spu.trends.eight_week_trend.change_percentage)
    .filter(change => change !== null);
  
  const fourWeekAverageChange = fourWeekChanges.length > 0
    ? fourWeekChanges.reduce((sum, change) => sum + change, 0) / fourWeekChanges.length
    : null;
  
  const eightWeekAverageChange = eightWeekChanges.length > 0
    ? eightWeekChanges.reduce((sum, change) => sum + change, 0) / eightWeekChanges.length
    : null;
  
  // 找出表现最好和最差的SPU
  const sortedByWmape = [...validSpus].sort((a, b) => a.metrics.average_wmape - b.metrics.average_wmape);
  const topPerformingSpus = sortedByWmape.slice(0, 3).map(spu => spu.spu_id);
  const bottomPerformingSpus = sortedByWmape.slice(-3).map(spu => spu.spu_id);
  
  return {
    metadata: {
      analysis_id: `anal_${Date.now()}`,
      timestamp: new Date().toISOString(),
      prediction_id: processedData.metadata?.prediction_id || "unknown",
      version: "v1.0",
      total_spus: spuAnalyses.length,
      average_wmape: averageWmape
    },
    spu_analyses: spuAnalyses,
    overall_trends: {
      four_week_average_change: fourWeekAverageChange,
      eight_week_average_change: eightWeekAverageChange,
      top_performing_spus: topPerformingSpus,
      bottom_performing_spus: bottomPerformingSpus
    }
  };
}
```

### 4.5 报告生成函数

```javascript
/**
 * 生成HTML报告
 * @param {Object} analysisResults - 分析结果
 * @returns {string} HTML报告
 */
function generateHtmlReport(analysisResults) {
  // 生成SPU表格行
  const spuTableRows = analysisResults.spu_analyses.map(spu => {
    const wmapePercentage = spu.metrics.average_wmape 
      ? `${(spu.metrics.average_wmape * 100).toFixed(2)}%` 
      : "N/A";
    
    const fourWeekTrend = spu.trends.four_week_trend;
    const eightWeekTrend = spu.trends.eight_week_trend;
    
    const fourWeekTrendText = fourWeekTrend.change_percentage !== null
      ? `${fourWeekTrend.direction} ${(fourWeekTrend.change_percentage * 100).toFixed(2)}%`
      : "N/A";
    
    const eightWeekTrendText = eightWeekTrend.change_percentage !== null
      ? `${eightWeekTrend.direction} ${(eightWeekTrend.change_percentage * 100).toFixed(2)}%`
      : "N/A";
    
    const performanceClass = {
      "优秀": "performance-excellent",
      "良好": "performance-good",
      "一般": "performance-fair",
      "较差": "performance-poor"
    }[spu.metrics.performance_rating] || "";
    
    return `
      <tr class="${performanceClass}">
        <td>${spu.spu_id}</td>
        <td>${spu.metrics.total_records}</td>
        <td>${wmapePercentage}</td>
        <td>${spu.metrics.performance_rating}</td>
        <td>${spu.metrics.model}</td>
        <td>${fourWeekTrendText}</td>
        <td>${eightWeekTrendText}</td>
      </tr>
    `;
  }).join('');
  
  // 生成HTML报告
  return `
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>SPU预测效果分析报告</title>
      <style>
        /* 样式省略，与之前报告相同 */
      </style>
    </head>
    <body>
      <div class="container">
        <h1>SPU预测效果分析报告</h1>
        
        <div class="summary">
          <h2>1. 数据概览</h2>
          <div class="summary-item"><strong>总数据条数:</strong> ${analysisResults.metadata.total_spus * 14}条</div>
          <div class="summary-item"><strong>参与预测的SPU数量:</strong> ${analysisResults.metadata.total_spus}个</div>
          <div class="summary-item"><strong>数据类型:</strong> 实时预测数据</div>
          <div class="summary-item"><strong>分析日期:</strong> ${new Date(analysisResults.metadata.timestamp).toLocaleDateString()}</div>
          <div class="summary-item"><strong>分析版本:</strong> ${analysisResults.metadata.version}</div>
        </div>
        
        <!-- 其他内容省略，与之前报告相同 -->
        
        <h2>3. 所有SPU详细预测效果</h2>
        <div class="scrollable-table">
          <table>
            <thead>
              <tr>
                <th>SPU编号</th>
                <th>预测记录数</th>
                <th>平均WMAPE</th>
                <th>性能评价</th>
                <th>使用模型</th>
                <th>4周走势 (4月2日/3月5日)</th>
                <th>8周走势 (4月30日/3月5日)</th>
              </tr>
            </thead>
            <tbody>
              ${spuTableRows}
            </tbody>
          </table>
        </div>
        
        <!-- 其他内容省略，与之前报告相同 -->
        
        <div class="footer">
          <p>© 2026 SPU预测分析报告 | 生成时间：${new Date(analysisResults.metadata.timestamp).toLocaleString()}</p>
        </div>
      </div>
    </body>
    </html>
  `;
}
```

### 4.6 版本管理函数

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

## 5. 前端调用示例

### 5.1 基本调用流程

```javascript
// 1. 获取预测数据
const predictionData = await fetchPredictionData('pred_20260312_001');

// 2. 处理数据
const processedData = processData(predictionData);

// 3. 分析数据
const analysisResults = analyzeData(processedData);

// 4. 生成报告
const htmlReport = generateHtmlReport(analysisResults);

// 5. 保存报告
const version = saveReport(analysisResults, htmlReport);

// 6. 显示报告
const reportContainer = document.getElementById('report-container');
reportContainer.innerHTML = htmlReport;

// 7. 提供下载链接
const downloadLink = document.createElement('a');
downloadLink.href = URL.createObjectURL(new Blob([htmlReport], { type: 'text/html' }));
downloadLink.download = `final_spu_analysis_report_${version}.html`;
downloadLink.textContent = '下载报告';
document.getElementById('download-section').appendChild(downloadLink);
```

### 5.2 版本管理调用

```javascript
// 获取版本历史
const history = getVersionHistory();

// 显示版本历史
const historyList = document.getElementById('version-history');
historyList.innerHTML = history.map(item => `
  <li>
    <a href="#" data-version="${item.version}">${item.version} (${new Date(item.timestamp).toLocaleString()})</a>
    <span>SPU数量: ${item.total_spus}</span>
  </li>
`).join('');

// 加载指定版本报告
document.addEventListener('click', async (e) => {
  if (e.target.dataset.version) {
    const version = e.target.dataset.version;
    const report = getReportByVersion(version);
    
    if (report.html) {
      const reportContainer = document.getElementById('report-container');
      reportContainer.innerHTML = report.html;
    }
  }
});
```

## 6. 性能优化策略

### 6.1 数据处理优化
- **分批处理**：对于大量数据，采用分批处理的方式，避免阻塞主线程
- **缓存机制**：缓存处理结果，避免重复计算
- **Web Workers**：使用Web Workers处理大量数据计算，提高性能

### 6.2 存储优化
- **压缩存储**：对存储的数据进行压缩，减少存储空间
- **过期策略**：设置数据过期时间，自动清理旧数据
- **IndexedDB**：对于大量数据，使用IndexedDB替代localStorage

### 6.3 网络优化
- **数据压缩**：服务端对数据进行压缩，减少传输时间
- **增量更新**：只传输变化的数据，减少数据传输量
- **预加载**：提前加载可能需要的数据，提高响应速度

## 7. 错误处理策略

### 7.1 数据错误处理
- **数据验证**：对输入数据进行严格验证，确保数据格式正确
- **错误提示**：当数据错误时，提供清晰的错误提示
- **降级处理**：当数据不完整时，采用降级策略，确保报告能够生成

### 7.2 网络错误处理
- **重试机制**：网络请求失败时，自动重试
- **离线处理**：支持离线模式，使用缓存数据
- **错误日志**：记录网络错误，便于排查问题

### 7.3 计算错误处理
- **边界情况处理**：处理除数为零、数据缺失等边界情况
- **异常捕获**：捕获计算过程中的异常，确保程序不会崩溃
- **结果验证**：验证计算结果的合理性，避免异常值

## 8. 结论

本方案通过设计合理的数据结构和处理流程，实现了从预测数据到分析报告的端到端流程。通过前端数据处理和分析计算，可以确保分析结果与最新的预测数据保持一致，同时提高分析的实时性和灵活性。

通过性能优化和错误处理策略，可以确保系统在处理大量数据时的性能和稳定性。同时，通过版本管理机制，可以确保报告的可追溯性和可管理性。
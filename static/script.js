// repair_package_v1_2_fix/static/script.js
(function () {
  // ----------------------------
  // 1. 头像 SVG (嵌入式数据 URL)
  // ----------------------------
  // 用户头像: 简单的人物图标
  const userSVG = `
  <svg xmlns='http://www.w3.org/2000/svg' width='28' height='28' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'>
    <circle cx='12' cy='8' r='4' fill='#1D4ED8'/>
    <path d='M4 22c0-4 4-6 8-6s8 2 8 6' fill='none' stroke='#1D4ED8'/>
  </svg>`;

  // AI 助手头像: 机器人/AI 芯片图标
  const aiSVG = `
  <svg xmlns='http://www.w3.org/2000/svg' width='28' height='28' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'>
    <path d='M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2'></path>
    <rect x='8' y='2' width='8' height='4' rx='1' ry='1' fill='#1D4ED8'></rect>
    <line x1='12' y1='18' x2='12' y2='10' stroke='#1D4ED8'></line>
    <line x1='8' y1='14' x2='16' y2='14' stroke='#1D4ED8'></line>
  </svg>`;

  // 将头像应用于初始消息
  // 注意：此处不再通过 img.src 设置，而是直接在 appendMessage 中嵌入 SVG
  // document.getElementById('avatarUser').src = 'data:image/svg+xml;utf8,' + encodeURIComponent(userSVG);
  // document.getElementById('avatarAI').src = 'data:image/svg+xml;utf8,' + encodeURIComponent(aiSVG);


  // ----------------------------
  // 2. DOM 元素 & 常量
  // ----------------------------
  const chatArea = document.getElementById('chatArea');
  const userQueryInput = document.getElementById('user-query-input'); 
  const sendBtn = document.getElementById('send-btn'); 
  const dataTableContainer = document.getElementById('dataTable');
  const sqlContentPre = document.getElementById('sqlContent');
  const copySqlBtn = document.getElementById('copySql');
  const chartAreaContainer = document.getElementById('chartArea');
  const insightContainer = document.getElementById('insight');
  const reportContentContainer = document.getElementById('reportContent');
  // const errorArea = document.getElementById('errorArea'); // 已移除，错误显示改用 loading-overlay
  // const errorMessageP = document.getElementById('errorMessage'); // 已移除

  // 模式选择按钮
  const analysisReportButton = document.getElementById('analysis-report-button'); // "分析报告" 按钮
  const regularAnswerButton = document.getElementById('regular-answer-button'); // "常规回答" 按钮

  let generateReportMode = false; // 默认值：常规回答模式 (不生成报告)

  const API_BASE_URL = window.location.origin; // 动态获取基础 URL

  // ----------------------------
  // 3. 辅助函数
  // ----------------------------

  /**
   * 更新模式选择按钮的视觉状态。
   * 根据 generateReportMode 的值，高亮当前选中的按钮。
   */
  function updateButtonStates() {
      if (analysisReportButton && regularAnswerButton) {
          if (generateReportMode) {
              analysisReportButton.classList.add('active');
              regularAnswerButton.classList.remove('active');
          } else {
              analysisReportButton.classList.remove('active');
              regularAnswerButton.classList.add('active');
          }
      }
  }

  /**
   * 将消息气泡添加到聊天区域。
   * @param {string} type - 'user' 或 'assistant'
   * @param {string} content - 消息的 HTML 内容
   */
  function appendMessage(type, content) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${type}`;

    // 使用 div 来包裹 SVG，而不是 img 标签
    const avatarDiv = document.createElement('div'); 
    avatarDiv.className = 'avatar';
    avatarDiv.innerHTML = type === 'user'
      ? userSVG
      : aiSVG;
    messageDiv.appendChild(avatarDiv);

    const bubbleDiv = document.createElement('div');
    bubbleDiv.className = 'bubble';
    bubbleDiv.innerHTML = content;
    messageDiv.appendChild(bubbleDiv);

    chatArea.appendChild(messageDiv);
    chatArea.scrollTop = chatArea.scrollHeight; // 滚动到底部
  }

  /**
   * 在加载叠加层中显示错误消息。
   * @param {string} message
   */
  function displayError(message) {
    const errorOverlay = document.getElementById('loading-overlay'); 
    const loadingMessage = document.getElementById('loading-message'); 
    if (errorOverlay && loadingMessage) {
        loadingMessage.innerHTML = `<i class="fas fa-exclamation-circle" style="color: #F44336; margin-right: 10px;"></i><span style="color: #F44336;">${message}</span>`;
        errorOverlay.classList.add('show');
        errorOverlay.style.backgroundColor = 'rgba(255, 255, 255, 0.98)'; 
        setTimeout(() => {
            errorOverlay.classList.remove('show');
            loadingMessage.textContent = ''; 
        }, 5000);
    } else {
        console.error("无法显示错误信息，因为加载叠加层或消息元素不存在。", message);
        alert("错误: " + message);
    }
  }

  /**
   * 清除所有动态结果部分。
   */
  function clearResults() {
    dataTableContainer.innerHTML = '';
    sqlContentPre.textContent = '无 SQL 信息';
    chartAreaContainer.innerHTML = '<h4 class="card-title">图表</h4><div class="chart-placeholder">暂无图表</div>';
    insightContainer.innerHTML = '<h4 class="card-title">洞察</h4><p>等待分析结果...</p>';
    reportContentContainer.innerHTML = '无报告内容';
  }

  /**
   * 渲染数据表。
   * @param {Array<Object>} data
   * @param {Array<string>} columns
   */
  function renderDataTable(data, columns) {
    dataTableContainer.innerHTML = '<h4 class="card-title">数据表</h4>';
    if (!data || data.length === 0) {
      dataTableContainer.innerHTML += '<p>暂无数据</p>';
      return;
    }

    const tableDiv = document.createElement('div');
    tableDiv.className = 'table-responsive';
    const table = document.createElement('table');
    table.className = 'table';

    const thead = document.createElement('thead');
    const trHead = document.createElement('tr');
    columns.forEach(col => {
      const th = document.createElement('th');
      th.textContent = col;
      trHead.appendChild(th);
    });
    thead.appendChild(trHead);
    table.appendChild(thead);

    const tbody = document.createElement('tbody');
    data.forEach(row => {
      const tr = document.createElement('tr');
      columns.forEach(col => {
        const td = document.createElement('td');
        td.textContent = row[col] != null ? String(row[col]) : '';
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    tableDiv.appendChild(table);
    dataTableContainer.appendChild(tableDiv);
  }

  /**
   * 从 chart_option 渲染一个简单的条形图。
   * 这是一个基于 SVG 的基本渲染器。对于复杂的图表，请集成 ECharts/Chart.js。
   * @param {Object} chartOption
   */
  function renderSimpleChart(chartOption) {
    chartAreaContainer.innerHTML = '<h4 class="card-title">图表</h4>';
    if (!chartOption || !chartOption.series || chartOption.series.length === 0) {
        chartAreaContainer.innerHTML += '<div class="chart-placeholder">暂无图表数据或配置无效</div>';
        return;
    }

    const titleText = chartOption.title?.text || '图表';
    const xAxisData = chartOption.xAxis?.data || [];
    const seriesData = chartOption.series[0]?.data || []; // 简化起见，假设只有第一个系列

    const chartDiv = document.createElement('div');
    chartDiv.className = 'simple-chart-display';
    chartDiv.style.height = '200px'; // 简单图表的固定高度
    chartDiv.style.width = '100%';
    chartDiv.style.display = 'flex';
    chartDiv.style.flexDirection = 'column';
    chartDiv.style.alignItems = 'center';

    const chartTitle = document.createElement('h5');
    chartTitle.textContent = titleText;
    chartTitle.style.marginBottom = '10px';
    chartDiv.appendChild(chartTitle);

    const barsContainer = document.createElement('div');
    barsContainer.style.display = 'flex';
    barsContainer.style.alignItems = 'flex-end';
    barsContainer.style.justifyContent = 'space-around';
    barsContainer.style.width = '100%';
    barsContainer.style.height = 'calc(100% - 30px)'; // 调整高度以适应标题

    // 查找最大值以进行缩放
    const maxVal = Math.max(...seriesData);
    
    xAxisData.forEach((label, index) => {
        const value = seriesData[index] || 0;
        const barHeight = maxVal > 0 ? (value / maxVal) * 80 + 10 : 10; // 缩放范围 10-90% 以获得视觉效果
        const barWrap = document.createElement('div');
        barWrap.style.display = 'flex';
        barWrap.style.flexDirection = 'column';
        barWrap.style.alignItems = 'center';
        barWrap.style.margin = '0 5px';

        const bar = document.createElement('div');
        bar.style.width = '25px';
        bar.style.height = `${barHeight}%`;
        bar.style.backgroundColor = '#1D4ED8';
        bar.style.borderRadius = '3px';
        bar.style.marginBottom = '5px';
        bar.title = `${label}: ${value}`; // 单个条形的工具提示

        const barLabel = document.createElement('span');
        barLabel.textContent = label;
        barLabel.style.fontSize = '0.7em';
        barLabel.style.color = '#555';
        barLabel.style.textAlign = 'center';

        barWrap.appendChild(bar);
        barWrap.appendChild(barLabel);
        barsContainer.appendChild(barWrap);
    });

    chartDiv.appendChild(barsContainer);
    chartAreaContainer.appendChild(chartDiv);
  }

  /**
   * 处理并渲染来自后端的响应。
   * @param {Object} payload - 来自后端的标准化 JSON 响应。
   */
  function renderBackendResponse(payload) {
    clearResults(); // 清除之前的结

    if (payload.error) {
      displayError(payload.error);
      return;
    }

    // 洞察
    if (payload.insight) {
      insightContainer.innerHTML = `<h4 class="card-title">洞察</h4><p>${payload.insight}</p>`;
    } else {
      insightContainer.innerHTML = `<h4 class="card-title">洞察</h4><p>暂无洞察信息。</p>`;
    }

    // SQL
    sqlContentPre.textContent = payload.sql || '无 SQL 信息';

    // 图表
    if (payload.chart_option && Object.keys(payload.chart_option).length > 0) {
      // 对于真实的应用程序，你将在此处初始化 ECharts：
      // const myChart = echarts.init(document.getElementById('chartArea').querySelector('div'));
      // myChart.setOption(payload.chart_option);
      renderSimpleChart(payload.chart_option); // 使用内置的简单渲染器进行演示
    } else {
      chartAreaContainer.innerHTML = '<h4 class="card-title">图表</h4><div class="chart-placeholder">暂无图表</div>';
    }

    // 数据表
    renderDataTable(payload.data, payload.columns);

    // 报告 HTML
    if (payload.report_html) {
      reportContentContainer.innerHTML = payload.report_html;
    } else {
      reportContentContainer.innerHTML = '无报告内容';
    }
  }

  // ----------------------------
  // 4. 事件监听器
  // ----------------------------

  // 发送按钮点击
  sendBtn.addEventListener('click', async () => {
    const query = userQueryInput.value.trim();
    if (!query) {
      displayError("请输入你的查询问题。");
      return;
    }

    appendMessage('user', query); // 将用户查询添加到聊天历史
    userQueryInput.value = ''; // 清空输入框

    // 显示加载叠加层
    const loadingOverlay = document.getElementById('loading-overlay');
    const loadingMessage = document.getElementById('loading-message');
    if (loadingOverlay && loadingMessage) {
        loadingMessage.textContent = '正在努力思考中，请稍候...';
        loadingOverlay.classList.add('show');
        loadingOverlay.style.backgroundColor = 'rgba(255, 255, 255, 0.92)'; // 重置加载背景颜色
    }


    try {
      const response = await fetch(`${API_BASE_URL}/api/execute-query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: query, generate_report: generateReportMode }) // 发送当前模式状态
      });

      const payload = await response.json();

      // 将助手的通用响应添加到聊天历史
      let assistantChatResponse = "好的，我已经处理了你的请求。";
      if (payload.error) {
          assistantChatResponse = `请求处理失败：${payload.error}`;
      } else if (generateReportMode && payload.report_html) { // 如果是报告模式且报告存在
          assistantChatResponse = `已为您生成分析报告，请查看右侧报告区域。`;
      } else if (!generateReportMode && payload.insight) { // 如果是常规回答模式且有洞察
          assistantChatResponse = `这是根据您的请求得到的洞察：<br><strong>${payload.insight.substring(0, 100)}...</strong>`;
      } else { // 兜底消息
          assistantChatResponse = `已处理您的请求。`;
      }
      appendMessage('assistant', assistantChatResponse);
      
      renderBackendResponse(payload); // 在面板中渲染详细结果

    } catch (e) {
      console.error('获取数据出错:', e);
      displayError(`与后端通信失败：${e.message}. 请检查网络或稍后重试。`);
      appendMessage('assistant', `抱歉，我无法完成您的请求。与后端服务通信出现问题：${e.message}`);
    } finally {
      // 隐藏加载叠加层
      const loadingOverlay = document.getElementById('loading-overlay');
      if (loadingOverlay) {
        loadingOverlay.classList.remove('show');
      }
    }
  });

  // 允许使用 Enter 键发送查询 (Shift+Enter 用于换行)
  userQueryInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault(); // 阻止换行
      sendBtn.click();
    }
  });

  // 复制 SQL 按钮功能
  copySqlBtn.addEventListener('click', () => {
    const sqlText = sqlContentPre.textContent;
    if (sqlText && sqlText !== '无 SQL 信息') {
      navigator.clipboard.writeText(sqlText)
        .then(() => alert('SQL 已复制到剪贴板！'))
        .catch(err => console.error('无法复制 SQL：', err));
    }
  });

  // 模式选择按钮的事件监听器
  if (analysisReportButton && regularAnswerButton) {
      analysisReportButton.addEventListener('click', () => {
          generateReportMode = true; // 设置为报告模式
          updateButtonStates(); // 更新按钮视觉状态
      });

      regularAnswerButton.addEventListener('click', () => {
          generateReportMode = false; // 设置为常规回答模式
          updateButtonStates(); // 更新按钮视觉状态
      });
  }

  // ----------------------------
  // 5. 初始状态 / 后端健康检查
  // ----------------------------
  /**
   * Ping 后端健康端点并更新状态。
   */
  async function checkBackendHealth() {
    try {
      const response = await fetch(`${API_BASE_URL}/api/health`);
      const data = await response.json();
      const statusIndicatorDB = document.getElementById('status-indicator-db'); 
      const statusIndicatorAI = document.getElementById('status-indicator-ai');

      if (statusIndicatorDB && statusIndicatorAI) {
        if (data.database_status === 'connected') {
            statusIndicatorDB.classList.remove('disconnected');
            statusIndicatorDB.classList.add('connected');
        } else {
            statusIndicatorDB.classList.remove('connected');
            statusIndicatorDB.classList.add('disconnected');
        }

        if (data.llm_service_status === 'connected') {
            statusIndicatorAI.classList.remove('disconnected');
            statusIndicatorAI.classList.add('connected');
        } else {
            statusIndicatorAI.classList.remove('connected');
            statusIndicatorAI.classList.add('disconnected');
        }
      }

    } catch (e) {
      console.error('无法连接到后端健康端点:', e);
      const statusIndicatorDB = document.getElementById('status-indicator-db');
      const statusIndicatorAI = document.getElementById('status-indicator-ai');
      if (statusIndicatorDB) {
          statusIndicatorDB.classList.remove('connected');
          statusIndicatorDB.classList.add('disconnected');
      }
      if (statusIndicatorAI) {
          statusIndicatorAI.classList.remove('connected');
          statusIndicatorAI.classList.add('disconnected');
      }
    }
  }

  // 页面加载时的初始设置
  updateButtonStates(); // 设置按钮的初始激活状态 (默认是常规回答)
  checkBackendHealth(); // 检查后端健康状态
  setInterval(checkBackendHealth, 10000); // 每 10 秒重新检查健康状况
})();
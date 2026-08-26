const state = {
  selectionType: "all",
  resolvedSelection: null,
  currentRunId: null,
  activeRunId: null,
  currentRunStatus: "idle",
  pollingTimer: null,
  configs: [],
  resultLoadedFor: null,
  linuxOps: null,
  startingRun: false,
  stoppingRun: false,
  actionBusy: false,
  clientLogs: [],
  pendingLogTimer: null,
};

const ACTIVE_STATUSES = new Set(["queued", "running", "stopping"]);

function el(id) {
  return document.getElementById(id);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function nowIso() {
  return new Date().toISOString();
}

function isActiveRunStatus(status) {
  return ACTIVE_STATUSES.has(status || "");
}

function stripHeroStats() {
  document.querySelectorAll(".hero-stats").forEach((node) => node.remove());
}

function parseRunTime(raw) {
  if (!raw) return null;
  const value = String(raw).trim();
  if (!value) return null;
  const normalized = value.includes("T")
    ? value
    : value.replace(" ", "T");
  const withZone = normalized.endsWith("Z") ? normalized : `${normalized}Z`;
  const date = new Date(withZone);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatDateTime(raw) {
  const date = parseRunTime(raw);
  if (!date) return "-";
  return date.toLocaleString("zh-CN", { hour12: false });
}

function formatDurationMs(ms) {
  if (!Number.isFinite(ms) || ms < 0) return "-";
  const totalSeconds = Math.floor(ms / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) return `${hours}小时${minutes}分${seconds}秒`;
  if (minutes > 0) return `${minutes}分${seconds}秒`;
  return `${seconds}秒`;
}

function setButtonBusy(buttonId, isBusy, busyLabel, idleLabel) {
  const button = el(buttonId);
  if (!button) return;
  button.disabled = !!isBusy;
  if (busyLabel && idleLabel) {
    button.textContent = isBusy ? busyLabel : idleLabel;
  }
}

function setRunFeedback(message = "", tone = "info", visible = true) {
  const feedback = el("runFeedback");
  if (!feedback) return;
  feedback.className = `feedback feedback-${tone}${visible ? "" : " hidden"}`;
  feedback.textContent = message;
}

function setStartButtonBusy(isBusy, label = "启动任务") {
  setButtonBusy("startJobBtn", isBusy, "提交中...", label);
}

function setStopBusy(isBusy) {
  setButtonBusy("stopJobBtn", isBusy, "停止中...", "停止任务");
}

function syncRunActionButtons() {
  const activeRun = isActiveRunStatus(state.currentRunStatus);
  setStartButtonBusy(activeRun || state.startingRun || state.actionBusy);
  setButtonBusy("resolveSelectionBtn", activeRun || state.actionBusy);
  setStopBusy(state.stoppingRun);
}

function renderLogs(logs, emptyText = "当前暂无可展示日志") {
  if (!logs.length) {
    return `<div class="log-entry">${escapeHtml(emptyText)}</div>`;
  }
  return logs
    .map((log) => {
      const css = log.level === "error" ? "log-entry error" : "log-entry";
      const prefix = [log.source, log.timestamp || log.created_at].filter(Boolean).join(" | ");
      const head = prefix ? `<span class="log-time">${escapeHtml(prefix)}</span>` : "";
      return `<div class="${css}">${head}${escapeHtml(log.message)}</div>`;
    })
    .join("");
}

function pushLocalLog(message, level = "info") {
  state.clientLogs.unshift({
    source: "前端",
    timestamp: nowIso(),
    message,
    level,
  });
  state.clientLogs = state.clientLogs.slice(0, 20);
}

function clearPendingClientLogs() {
  if (state.pendingLogTimer) {
    clearInterval(state.pendingLogTimer);
    state.pendingLogTimer = null;
  }
}

function startPendingClientLogs(message) {
  clearPendingClientLogs();
  pushLocalLog(message, "info");
  state.pendingLogTimer = setInterval(() => {
    pushLocalLog(`${message} 处理中...`, "info");
  }, 2500);
}

function setSelectionType(nextType) {
  state.selectionType = nextType || "all";
  document.querySelectorAll(".segment-btn").forEach((button) => {
    button.classList.toggle("active", button.dataset.selection === state.selectionType);
  });
}

function getSelectionPayload() {
  return { selection_type: "all" };
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || `Request failed: ${response.status}`);
  }
  return response.json();
}

function setRunStatus(run) {
  const status = run?.status || "idle";
  state.currentRunStatus = status;
  const badge = el("runBadge");
  if (badge) {
    badge.className = `status status-${status}`;
    badge.textContent = status;
  }
  const heroRunStatus = el("heroRunStatus");
  if (heroRunStatus) heroRunStatus.textContent = status;
  syncRunActionButtons();
}

function updateRunSummary(run) {
  const summary = run?.summary || {};
  // During running, unprocessed SPUs must not be treated as failed.
  // Failure count should be based on processed vs success, and final summary when available.
  const active = isActiveRunStatus(run?.status);
  const processedFailures = Math.max((run?.processed_count || 0) - (run?.success_count || 0), 0);
  const failedSpus = active
    ? processedFailures
    : (summary.failed_spus ?? processedFailures);
  const policySummary = (summary.policy_standard_spus != null || summary.policy_conservative_spus != null)
    ? `${summary.policy_standard_spus || 0}标准 / ${summary.policy_conservative_spus || 0}保守`
    : "-";
  const startedAt = parseRunTime(run?.started_at);
  const finishedAt = parseRunTime(run?.finished_at);
  const now = new Date();
  const durationMs = startedAt ? ((finishedAt || now).getTime() - startedAt.getTime()) : NaN;
  const items = [
    ["触发方式", run?.trigger_source || "-"],
    ["模式", run?.mode || "-"],
    ["策略", policySummary],
    ["启动时间", formatDateTime(run?.started_at)],
    ["结束时间", formatDateTime(run?.finished_at)],
    ["耗时", formatDurationMs(durationMs)],
    ["平均 WMAPE", summary.average_wmape ? `${(summary.average_wmape * 100).toFixed(2)}%` : "-"],
    ["失败 SPU", failedSpus],
  ];
  const container = el("runSummary");
  if (!container) return;
  container.innerHTML = items
    .map(([label, value]) => `<div class="summary-item"><span class="muted">${label}</span><strong>${value}</strong></div>`)
    .join("");
}

function updateRunHeader(run) {
  if (!run) return;
  setRunStatus(run);
  const entries = [
    ["progressValue", `${run.progress || 0}%`],
    ["processedValue", `${run.processed_count || 0} / ${run.total_count || 0}`],
    ["successValue", `${run.success_count || 0}`],
    ["currentSpuValue", run.current_spu || "-"],
    ["heroLastRun", run.id ? run.id.slice(0, 8) : "暂无"],
  ];
  entries.forEach(([id, value]) => {
    const node = el(id);
    if (node) node.textContent = value;
  });
  const bar = el("progressBar");
  if (bar) bar.style.width = `${run.progress || 0}%`;
  const stopButton = el("stopJobBtn");
  if (stopButton) stopButton.classList.toggle("hidden", !isActiveRunStatus(run.status));
  updateRunSummary(run);
}

async function resolveSelection() {
  const result = await api("/api/spu-selection/resolve", {
    method: "POST",
    body: JSON.stringify(getSelectionPayload()),
  });
  state.resolvedSelection = result;
  const count = el("selectionCount");
  if (count) count.textContent = `${result.count} 个`;
  const preview = el("selectionPreview");
  if (!preview) return;
  if (!result.preview?.length) {
    preview.classList.add("muted");
    preview.textContent = "暂无可解析 SPU";
    return;
  }
  preview.classList.remove("muted");
  preview.innerHTML = result.preview.map((spu) => `<span class="pill">${escapeHtml(spu)}</span>`).join("");
}

async function startRun() {
  if (state.actionBusy || state.startingRun) return;
  state.startingRun = true;
  state.clientLogs = [];
  setStartButtonBusy(true);
  setRunFeedback("任务已提交，准备执行中...", "info", true);
  startPendingClientLogs("已提交任务");
  try {
    const result = await api("/api/forecast-jobs", {
      method: "POST",
      body: JSON.stringify({
        ...getSelectionPayload(),
        mode: el("modeSelect")?.value || "smart",
      }),
    });
    clearPendingClientLogs();
    state.currentRunId = result.run_id;
    state.activeRunId = result.run?.status && isActiveRunStatus(result.run.status) ? result.run_id : null;
    updateRunHeader(result.run);
    setRunFeedback("任务已启动，日志会自动刷新。", "success", true);
    await loadRunStatus();
    startPolling();
  } finally {
    state.startingRun = false;
    syncRunActionButtons();
  }
}

async function stopRun() {
  if (!state.currentRunId || state.stoppingRun) return;
  state.stoppingRun = true;
  setStopBusy(true);
  setRunFeedback("已发送停止请求...", "warning", true);
  try {
    const run = await api(`/api/forecast-jobs/${state.currentRunId}/stop`, { method: "POST" });
    updateRunHeader(run);
    await loadRunStatus();
  } finally {
    state.stoppingRun = false;
    syncRunActionButtons();
  }
}

async function loadRunStatus() {
  const runs = await api("/api/forecast-jobs?limit=1");
  if (!runs.length) {
    state.currentRunId = null;
    state.activeRunId = null;
    setRunStatus({ status: "idle" });
    const resetMap = [
      ["progressValue", "0%"],
      ["processedValue", "0 / 0"],
      ["successValue", "0"],
      ["currentSpuValue", "-"],
      ["heroLastRun", "暂无"],
    ];
    resetMap.forEach(([id, value]) => {
      const node = el(id);
      if (node) node.textContent = value;
    });
    const bar = el("progressBar");
    if (bar) bar.style.width = "0%";
    setRunFeedback("", "info", false);
    await Promise.all([loadLinuxOps(), loadExecutionLogs()]);
    return;
  }

  const run = runs[0];
  state.currentRunId = run.id;
  state.activeRunId = isActiveRunStatus(run.status) ? run.id : null;
  updateRunHeader(run);

  if (run.status === "queued") setRunFeedback("任务已排队。", "info", true);
  if (run.status === "running") setRunFeedback("任务执行中。", "success", true);
  if (run.status === "stopping") setRunFeedback("任务停止中。", "warning", true);
  if (run.status === "completed") setRunFeedback("任务已完成。", "success", true);
  if (run.status === "failed") setRunFeedback("任务执行失败，请查看任务状态。", "warning", true);

  await Promise.all([loadRunSpus(), loadLinuxOps(), loadExecutionLogs()]);
  if (!isActiveRunStatus(run.status) && state.pollingTimer) {
    clearInterval(state.pollingTimer);
    state.pollingTimer = null;
  }
}

function startPolling() {
  if (state.pollingTimer) clearInterval(state.pollingTimer);
  state.pollingTimer = setInterval(() => loadRunStatus().catch(handleError), 3000);
}

async function loadRunSpus() {
  if (!state.currentRunId) return;
  const spus = await api(`/api/forecast-jobs/${state.currentRunId}/spus`);
  const container = el("spuList");
  if (!container) return;
  if (!spus.length) {
    container.innerHTML = `<div class="stack-item muted">暂无 SPU 状态</div>`;
    return;
  }
  container.innerHTML = spus.map((item) => {
    const wmape = item.validation_wmape == null ? "-" : `${(item.validation_wmape * 100).toFixed(2)}%`;
    return `
      <article class="stack-item">
        <h4>${escapeHtml(item.spu)}</h4>
        <p>状态：${escapeHtml(item.status)}</p>
        <p>模型：${escapeHtml(item.winner_algo || "-")}</p>
        <p>WMAPE：${escapeHtml(wmape)}</p>
        <p>${escapeHtml(item.message || "")}</p>
      </article>
    `;
  }).join("");
}

async function loadLinuxOps() {
  const [ops, historyRuns] = await Promise.all([
    api("/api/linux-ops"),
    api("/api/forecast-jobs/history?limit=8"),
  ]);
  state.linuxOps = ops;

  const summary = el("linuxOpsSummary");
  const sourceValue = el("linuxLogSourceValue");
  const nextRunValue = el("linuxNextRunValue");
  const serviceList = el("linuxServiceList");
  const historyJobList = el("historyJobList");

  if (summary) summary.textContent = ops.captured_at ? `更新于 ${ops.captured_at}` : "已刷新";
  if (sourceValue) sourceValue.textContent = ops.logs?.source?.label || "服务日志";
  if (nextRunValue) {
    nextRunValue.textContent = ops.next_schedule
      ? `${ops.next_schedule.config_name} · ${ops.next_schedule.next_run_text}`
      : "暂无启用的定期执行";
  }

  const services = ops.services || [];
  if (serviceList) {
    if (!services.length) {
      serviceList.innerHTML = `<div class="stack-item muted">暂无系统服务状态</div>`;
    } else {
      serviceList.innerHTML = services.map((service) => {
        const stateText = service.status_text || `${service.active_state || "unknown"} / ${service.sub_state || "unknown"}`;
        const statusClass =
          service.active_state === "active"
            ? "status-running"
            : service.active_state === "inactive"
              ? "status-idle"
              : service.available === false
                ? "status-failed"
                : "status-stopped";
        return `
          <article class="stack-item">
            <div class="preview-topline">
              <strong>${escapeHtml(service.description || service.unit)}</strong>
              <span class="status ${statusClass}">${escapeHtml(service.active_state || "unknown")}</span>
            </div>
            <p>单位：${escapeHtml(service.unit || "-")}</p>
            <p>状态：${escapeHtml(stateText)}</p>
            <p>启用：${escapeHtml(service.unit_file_state || "-")}</p>
            <p>下次触发：${escapeHtml(service.next_elapse_realtime || "n/a")}</p>
            <p>日志：${escapeHtml(service.log_path || "n/a")}</p>
          </article>
        `;
      }).join("");
    }
  }

  if (historyJobList) {
    if (!historyRuns.length) {
      historyJobList.innerHTML = `<div class="stack-item muted">暂无历史作业</div>`;
    } else {
      historyJobList.innerHTML = historyRuns.map((run) => `
        <article class="stack-item">
          <div class="preview-topline">
            <strong>${escapeHtml((run.id || "").slice(0, 8) || "-")}</strong>
            <span class="status status-${escapeHtml(run.status || "idle")}">${escapeHtml(run.status || "-")}</span>
          </div>
          <p>触发：${escapeHtml(run.trigger_source || "-")} | 模式：${escapeHtml(run.mode || "-")}</p>
          <p>进度：${escapeHtml(run.progress || 0)}% | 处理：${escapeHtml(run.processed_count || 0)} / ${escapeHtml(run.total_count || 0)}</p>
          <p>更新时间：${escapeHtml(run.updated_at || run.finished_at || run.started_at || "-")}</p>
        </article>
      `).join("");
    }
  }
}

async function loadExecutionLogs() {
  const container = el("logList");
  if (!container) return;
  const liveLogHint = el("liveLogHint");

  if (!state.activeRunId) {
    if (liveLogHint) liveLogHint.textContent = "当前仅显示运行中的任务日志";
    container.innerHTML = renderLogs([], "当前无运行任务日志。历史作业请在下方 Linux 运维状态查看。");
    container.scrollTop = 0;
    return;
  }

  let logs = [];
  try {
    logs = await api(`/api/forecast-jobs/${state.activeRunId}/logs?limit=200`);
  } catch (error) {
    console.warn("Failed to load run logs", error);
  }
  if (liveLogHint) liveLogHint.textContent = "当前仅显示运行中的任务日志";
  const mergedLogs = [...state.clientLogs, ...logs].slice(0, 120);
  container.innerHTML = renderLogs(mergedLogs, "运行中任务暂无日志输出");
  container.scrollTop = container.scrollHeight;
}

async function loadResults() {
  if (!state.currentRunId) {
    alert("暂无可查询的任务。");
    return;
  }
  const results = await api(`/api/forecast-results?run_id=${state.currentRunId}&limit=100`);
  const resultSummary = el("resultSummary");
  const resultsTableBody = el("resultsTableBody");
  if (!results.length) {
    if (resultSummary) resultSummary.textContent = "当前任务暂无结果数据。";
    if (resultsTableBody) resultsTableBody.innerHTML = `<tr><td colspan="6" class="muted">暂无结果</td></tr>`;
    return;
  }
  state.resultLoadedFor = state.currentRunId;
  if (resultSummary) {
    const models = [...new Set(results.map((item) => item.winner_algo).filter(Boolean))];
    resultSummary.innerHTML = models.length
      ? models.map((model) => `<span class="pill">${escapeHtml(model)}</span>`).join("")
      : "暂无模型摘要";
  }
  if (resultsTableBody) {
    resultsTableBody.innerHTML = results.map((row) => `
      <tr>
        <td>${escapeHtml(row.spu)}</td>
        <td>${escapeHtml(row.run_date)}</td>
        <td>${escapeHtml(row.forecast_target_date)}</td>
        <td>${escapeHtml(row.spu_forecast_value)}</td>
        <td>${escapeHtml(row.winner_algo || "-")}</td>
        <td>${row.validation_wmape == null ? "-" : `${(row.validation_wmape * 100).toFixed(2)}%`}</td>
      </tr>
    `).join("");
  }
}

async function loadConfigs() {
  const configs = await api("/api/forecast-configs");
  state.configs = configs;
  const list = el("configList");
  const select = el("scheduleConfigSelect");
  if (list) {
    list.innerHTML = !configs.length
      ? `<div class="stack-item muted">暂无配置模板</div>`
      : configs.map((config) => `
          <article class="stack-item">
            <h4>${escapeHtml(config.name)}</h4>
            <p>${escapeHtml(config.purpose || "未填写用途")}</p>
            <p>模式：${escapeHtml(config.mode)} | 选择方式：${escapeHtml(config.selection_type)}</p>
            <div class="actions"><button class="btn btn-secondary" onclick="runConfig('${config.id}')">立即执行</button></div>
          </article>
        `).join("");
  }
  if (select) {
    select.innerHTML = configs.length
      ? configs.map((config) => `<option value="${config.id}">${escapeHtml(config.name)}</option>`).join("")
      : `<option value="">暂无模板</option>`;
  }
}

async function saveConfig() {
  const payload = {
    name: el("configName")?.value.trim() || "",
    purpose: el("configPurpose")?.value.trim() || "",
    mode: el("modeSelect")?.value || "smart",
    ...getSelectionPayload(),
  };
  if (!payload.name) throw new Error("请先填写配置名称。");
  await api("/api/forecast-configs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (el("configName")) el("configName").value = "";
  if (el("configPurpose")) el("configPurpose").value = "";
  await loadConfigs();
  await loadSchedules();
}

async function runConfig(configId) {
  if (state.actionBusy || state.startingRun) return;
  state.startingRun = true;
  setStartButtonBusy(true, "模板启动中...");
  try {
    const result = await api(`/api/forecast-configs/${configId}/run`, { method: "POST" });
    state.currentRunId = result.run_id;
    state.activeRunId = result.run?.status && isActiveRunStatus(result.run.status) ? result.run_id : null;
    updateRunHeader(result.run);
    await loadRunStatus();
    startPolling();
  } finally {
    state.startingRun = false;
    syncRunActionButtons();
  }
}
window.runConfig = runConfig;

async function saveSchedule() {
  const configId = el("scheduleConfigSelect")?.value;
  if (!configId) throw new Error("请先选择模板。");
  await api("/api/forecast-schedules", {
    method: "POST",
    body: JSON.stringify({
      config_id: configId,
      weekday: Number(el("scheduleWeekday")?.value || 0),
      hour: Number(el("scheduleHour")?.value || 0),
      minute: Number(el("scheduleMinute")?.value || 0),
      timezone: "Asia/Shanghai",
      enabled: true,
    }),
  });
  await loadSchedules();
}

async function loadSchedules() {
  const schedules = await api("/api/forecast-schedules");
  const configMap = Object.fromEntries(state.configs.map((config) => [config.id, config]));
  const weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];
  const list = el("scheduleList");
  if (!list) return;
  if (!schedules.length) {
    list.innerHTML = `<div class="stack-item muted">暂无执行计划</div>`;
    return;
  }
  list.innerHTML = schedules.map((schedule) => `
    <article class="stack-item">
      <h4>${escapeHtml(configMap[schedule.config_id]?.name || schedule.config_id)}</h4>
      <p>${weekdays[schedule.weekday]} ${String(schedule.hour).padStart(2, "0")}:${String(schedule.minute).padStart(2, "0")}</p>
      <p>时区：${escapeHtml(schedule.timezone)} | 状态：${schedule.enabled ? "启用" : "停用"}</p>
      <p>下次执行：${escapeHtml(schedule.next_run_text || "暂无")}</p>
    </article>
  `).join("");
}

function handleError(error) {
  clearPendingClientLogs();
  setRunFeedback(`操作失败: ${error.message || String(error)}`, "warning", true);
  pushLocalLog(`操作失败: ${error.message || String(error)}`, "error");
  state.startingRun = false;
  state.stoppingRun = false;
  state.actionBusy = false;
  syncRunActionButtons();
}

function bindEvents() {
  document.querySelectorAll(".segment-btn").forEach((button) => {
    button.addEventListener("click", () => setSelectionType(button.dataset.selection));
  });
  el("resolveSelectionBtn")?.addEventListener("click", () => resolveSelection().catch(handleError));
  el("startJobBtn")?.addEventListener("click", () => startRun().catch(handleError));
  el("stopJobBtn")?.addEventListener("click", () => stopRun().catch(handleError));
  el("refreshLogsBtn")?.addEventListener("click", () => loadExecutionLogs().catch(handleError));
  el("refreshLinuxOpsBtn")?.addEventListener("click", () => loadLinuxOps().catch(handleError));
  el("loadResultsBtn")?.addEventListener("click", () => loadResults().catch(handleError));
  el("refreshConfigsBtn")?.addEventListener("click", async () => {
    await loadConfigs();
    await loadSchedules();
  });
  el("saveConfigBtn")?.addEventListener("click", () => saveConfig().catch(handleError));
  el("saveScheduleBtn")?.addEventListener("click", () => saveSchedule().catch(handleError));
}

async function bootstrap() {
  stripHeroStats();
  bindEvents();
  setSelectionType("all");
  setRunFeedback("", "info", false);
  await Promise.all([loadConfigs(), loadSchedules(), loadRunStatus(), loadLinuxOps(), loadExecutionLogs()]);
  if (state.currentRunId) startPolling();
}

bootstrap().catch(handleError);

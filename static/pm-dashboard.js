const data = {
  scopeIn: [
    "前端可发起一次 SPU 预测任务，并看到状态、进度、日志、结果摘要",
    "后端可执行任务并返回 queued/running/completed/failed 状态",
    "数据库稳定入库预测结果并支持 run_id/spu/run_date 查询",
    "至少跑通一条完整主链路：触发任务 -> 看到结果",
  ],
  scopeOut: [
    "SKU 细粒度预测优化",
    "交互式图表增强",
    "复杂告警与深度性能优化",
    "历史遗留入口全面重构",
  ],
  gates: [
    {
      item: "前端一次点击触发任务，3 秒级轮询看到状态变化",
      status: "pass",
      note: "已具备基础能力",
    },
    {
      item: "后端任务状态完整并可追踪",
      status: "pass",
      note: "queued/running/completed/failed 已有",
    },
    {
      item: "单个 SPU 执行成功并返回可读错误",
      status: "pass",
      note: "自动化回归通过（test_forecast_platform: 12 passed）",
    },
    {
      item: "结果稳定入库并可按 run_id 查询一致",
      status: "partial",
      note: "入库可用，建议补 3 次连续回归验证",
    },
    {
      item: "连续 3 次闭环稳定通过",
      status: "fail",
      note: "待真实数据库环境执行 3 次闭环回归",
    },
  ],
  board: {
    todo: [
      "补 MVP 闭环回归脚本：连续运行 3 次并比对入库行数",
      "统一结果查询口径（run_id/spu/run_date）并做前端可见验证",
      "补一页 MVP 验收记录文档",
    ],
    doing: [
      "围绕 SPU MVP 固定范围管理，不接入非 MVP 任务",
      "按“目标/范围/优先级/验收/时限/约束”模板执行里程碑推进",
    ],
    done: [
      "FastAPI 任务接口、状态轮询、日志查询能力就绪",
      "前端任务发起与结果摘要页面就绪",
      "数据库入库主流程打通",
      "SQL 选择已收紧为“仅允许单列 spu，不符合报错”",
    ],
    risk: [
      "代码存在新旧双主线，功能容易做在非当前主链路",
      "部分文档结论已过时，可能导致优先级误判",
    ],
    blocked: [
      "缺少连续 3 次闭环稳定性验证结果",
    ],
  },
  nextActions: [
    "固定 MVP 验收清单并按清单逐项打勾",
    "执行 3 次闭环回归，记录 run_id、状态、入库行数、查询一致性",
    "将结果查询接口扩展到 MVP 必要字段，避免前端只能看简版结果",
    "把当日风险和阻塞写入看板，确保不偏离 MVP 主目标",
    "仅在闭环通过后，再排期图表/告警/SKU 扩展",
  ],
};

function renderList(id, items) {
  const el = document.getElementById(id);
  el.innerHTML = items.map((item) => `<li>${item}</li>`).join("");
}

function renderGates() {
  const body = document.getElementById("gateTableBody");
  body.innerHTML = data.gates
    .map((g) => {
      const statusLabel = g.status === "pass" ? "通过" : g.status === "partial" ? "部分通过" : "未通过";
      return `
        <tr>
          <td>${g.item}</td>
          <td class="status ${g.status}">${statusLabel}</td>
          <td>${g.note}</td>
        </tr>
      `;
    })
    .join("");

  const passed = data.gates.filter((g) => g.status === "pass").length;
  const partial = data.gates.filter((g) => g.status === "partial").length;
  const score = Math.round(((passed + partial * 0.5) / data.gates.length) * 100);
  document.getElementById("gatePassRate").textContent = `${score}%`;
}

function buildSummaryText() {
  const today = new Date().toISOString().slice(0, 10);
  const gates = data.gates
    .map((g) => `- ${g.item} | ${g.status.toUpperCase()} | ${g.note}`)
    .join("\n");

  return [
    `# SPU MVP 项目总结 (${today})`,
    "",
    "## 阶段目标",
    "- 先完成 SPU MVP 闭环：前端触发 -> 后端执行 -> 数据库入库与查询",
    "",
    "## 范围内",
    ...data.scopeIn.map((x) => `- ${x}`),
    "",
    "## 范围外",
    ...data.scopeOut.map((x) => `- ${x}`),
    "",
    "## 门禁状态",
    gates,
    "",
    "## 下一步",
    ...data.nextActions.map((x, idx) => `${idx + 1}. ${x}`),
  ].join("\n");
}

async function copySummary() {
  const text = buildSummaryText();
  await navigator.clipboard.writeText(text);
  const btn = document.getElementById("copySummaryBtn");
  const old = btn.textContent;
  btn.textContent = "已复制";
  setTimeout(() => {
    btn.textContent = old;
  }, 1200);
}

function bootstrap() {
  renderList("scopeIn", data.scopeIn);
  renderList("scopeOut", data.scopeOut);
  renderGates();
  renderList("todoList", data.board.todo);
  renderList("doingList", data.board.doing);
  renderList("doneList", data.board.done);
  renderList("riskList", data.board.risk);
  renderList("blockedList", data.board.blocked);
  renderList("nextActions", data.nextActions);

  document.getElementById("copySummaryBtn").addEventListener("click", () => {
    copySummary().catch(() => {
      alert("复制失败，请手动复制页面内容。");
    });
  });
}

bootstrap();

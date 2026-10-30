const state = {
  docs: [],
  importMode: "file",
  file: null,
  asking: false,
  memoryLoaded: false,
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

function escapeHtml(text) {
  return String(text ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function inline(text) {
  return text
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\[(\d{1,2})\]/g, '<span class="cite" data-n="$1">$1</span>');
}

function markdown(text) {
  const lines = escapeHtml(text).split("\n");
  const out = [];
  let list = null;
  for (const raw of lines) {
    const line = raw.trimEnd();
    if (!line.trim()) {
      if (list) { out.push(`</${list}>`); list = null; }
      continue;
    }
    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) {
      if (list) { out.push(`</${list}>`); list = null; }
      const level = Math.min(heading[1].length + 2, 5);
      out.push(`<h${level}>${inline(heading[2])}</h${level}>`);
      continue;
    }
    const ul = line.match(/^\s*[-*]\s+(.*)$/);
    const ol = line.match(/^\s*\d+[.)]\s+(.*)$/);
    if (ul || ol) {
      const kind = ul ? "ul" : "ol";
      if (list !== kind) {
        if (list) out.push(`</${list}>`);
        out.push(`<${kind}>`);
        list = kind;
      }
      out.push(`<li>${inline((ul || ol)[1])}</li>`);
      continue;
    }
    if (list) { out.push(`</${list}>`); list = null; }
    out.push(`<p>${inline(line)}</p>`);
  }
  if (list) out.push(`</${list}>`);
  return out.join("");
}

async function api(path, options = {}) {
  const resp = await fetch(path, options);
  const text = await resp.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { detail: text }; }
  if (!resp.ok) throw new Error((data && data.detail) || `HTTP ${resp.status}`);
  return data;
}

function currentUser() {
  return ($("#user-id").value || "demo").trim() || "demo";
}

function currentFilters() {
  return {
    source_type: $("#filter-type").value,
    year_from: Number($("#filter-year").value) || 0,
  };
}

/* ---------------- 状态 ---------------- */
async function loadHealth() {
  try {
    const h = await api("/api/health");
    const seek = $("#pill-seekdb");
    if (h.seekdb.ok) {
      seek.className = "pill ok";
      seek.textContent = `seekdb ${h.seekdb.mode} · ${h.seekdb.documents} 篇 / ${h.seekdb.chunks} 片`;
    } else {
      seek.className = "pill bad";
      seek.textContent = "seekdb 未连接";
      seek.title = h.seekdb.error || "";
    }
    const mem = $("#pill-memory");
    if (h.powercontext.available) {
      mem.className = "pill ok";
      mem.textContent = "PowerContext 记忆已连接";
    } else {
      mem.className = "pill bad";
      mem.textContent = "PowerContext 未连接";
      mem.title = h.powercontext.error || "请先启动 powercontext server";
    }
    const llm = $("#pill-llm");
    llm.className = h.llm ? "pill ok" : "pill bad";
    llm.textContent = h.llm ? "DashScope 模型就绪" : "缺少 DASHSCOPE_API_KEY";
  } catch (err) {
    $("#pill-seekdb").className = "pill bad";
    $("#pill-seekdb").textContent = "服务异常";
  }
}

/* ---------------- 资料库 ---------------- */
async function loadDocs() {
  try {
    const data = await api("/api/documents");
    state.docs = data.documents || [];
  } catch (err) {
    state.docs = [];
  }
  renderDocs();
}

function renderDocs() {
  const type = $("#filter-type").value;
  const yearFrom = Number($("#filter-year").value) || 0;
  const docs = state.docs.filter(
    (d) => (type === "all" || d.source_type === type) && (!yearFrom || (d.year || 0) >= yearFrom)
  );
  const list = $("#doc-list");
  list.innerHTML = "";
  $("#doc-empty").classList.toggle("hidden", docs.length > 0);
  if (!state.docs.length) {
    $("#doc-empty").textContent = "还没有资料，点击「导入」添加论文或笔记。";
  } else if (!docs.length) {
    $("#doc-empty").textContent = "当前筛选条件下没有资料。";
  }

  for (const doc of docs) {
    const li = document.createElement("li");
    li.className = "doc";
    const tags = (doc.tags || "").split(",").filter(Boolean).slice(0, 3)
      .map((t) => `<span class="tag">${escapeHtml(t)}</span>`).join("");
    li.innerHTML = `
      <button class="del" title="删除">×</button>
      <h4>${escapeHtml(doc.title || "未命名")}</h4>
      <div class="meta">
        <span>${escapeHtml(doc.source_type || "note")}</span>
        ${doc.year ? `<span>${doc.year}</span>` : ""}
        <span>${doc.chunk_count || 0} 片</span>
        ${tags}
      </div>`;
    li.querySelector(".del").addEventListener("click", async (event) => {
      event.stopPropagation();
      if (!confirm(`删除《${doc.title}》及其全部索引片段？`)) return;
      try {
        await api(`/api/documents/${encodeURIComponent(doc.doc_id)}`, { method: "DELETE" });
        await loadDocs();
        await loadHealth();
      } catch (err) {
        alert(`删除失败：${err.message}`);
      }
    });
    li.addEventListener("click", () => {
      $("#question").value = `总结一下《${doc.title}》的核心观点`;
      $("#question").focus();
    });
    list.appendChild(li);
  }
}

/* ---------------- 提问 ---------------- */
function addUserTurn(text) {
  const turn = document.createElement("div");
  turn.className = "turn user";
  turn.innerHTML = `<div class="bubble">${escapeHtml(text)}</div>`;
  $("#chat").appendChild(turn);
  scrollChat();
}

function addAssistantCard(data) {
  const turn = document.createElement("div");
  turn.className = "turn";
  const card = document.createElement("div");
  card.className = "answer-card";
  const answer = document.createElement("div");
  answer.className = "answer";
  answer.innerHTML = markdown(data.answer || "");
  card.appendChild(answer);

  const cites = document.createElement("div");
  cites.className = "cites";
  if ((data.citations || []).length) {
    cites.innerHTML = "<h5>引用来源 · 由 seekdb 检索命中</h5>";
    for (const c of data.citations) {
      const row = document.createElement("div");
      row.className = "cite-card";
      row.dataset.n = c.n;
      row.innerHTML = `
        <div class="num">${c.n}</div>
        <div class="body">
          <p class="t">《${escapeHtml(c.title)}》</p>
          <p class="loc">${escapeHtml(c.section)}${c.page ? ` · 第 ${c.page} 页` : ""} · ${escapeHtml(c.source_type)}${c.year ? ` · ${c.year}` : ""}</p>
          <p class="snip">${escapeHtml(c.snippet)}…</p>
        </div>`;
      cites.appendChild(row);
    }
  } else {
    cites.innerHTML = '<h5>引用来源</h5><p class="empty">本次没有命中资料片段。</p>';
  }
  card.appendChild(cites);

  const mem = data.memory || {};
  const meta = document.createElement("div");
  meta.className = "meta-line";
  const memHits = (mem.hits || []).length;
  const memWritten = (mem.written || []).length;
  meta.innerHTML = `
    <span class="${mem.enabled ? "ok" : "warn"}">记忆：${mem.enabled ? `命中 ${memHits} 条 · 回写 ${memWritten} 条` : "未连接"}</span>
    <span>检索：${(data.trace && data.trace.mode) || "hybrid"}</span>
    ${data.trace && data.trace.keywords ? `<span>关键词：${escapeHtml(data.trace.keywords)}</span>` : ""}`;
  card.appendChild(meta);

  answer.addEventListener("click", (event) => {
    const chip = event.target.closest(".cite");
    if (!chip) return;
    const target = card.querySelector(`.cite-card[data-n="${chip.dataset.n}"]`);
    if (!target) return;
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    target.classList.add("flash");
    setTimeout(() => target.classList.remove("flash"), 1200);
  });

  turn.appendChild(card);
  $("#chat").appendChild(turn);
  scrollChat();
}

function addErrorTurn(message) {
  const turn = document.createElement("div");
  turn.className = "turn";
  turn.innerHTML = `<div class="answer-card"><div class="answer"><p>出错了：${escapeHtml(message)}</p></div></div>`;
  $("#chat").appendChild(turn);
  scrollChat();
}

function scrollChat() {
  const box = $("#chat");
  box.scrollTop = box.scrollHeight;
}

async function ask() {
  const question = $("#question").value.trim();
  if (!question || state.asking) return;
  const empty = $("#chat-empty");
  if (empty) empty.remove();
  state.asking = true;
  $("#ask-btn").disabled = true;
  $("#ask-btn").textContent = "检索中…";
  $("#question").value = "";
  addUserTurn(question);

  try {
    const data = await api("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, user_id: currentUser(), filters: currentFilters() }),
    });
    addAssistantCard(data);
    renderTrace(data.trace, data.memory);
    renderMemoryFromAsk(data.memory);
  } catch (err) {
    addErrorTurn(err.message);
  } finally {
    state.asking = false;
    $("#ask-btn").disabled = false;
    $("#ask-btn").textContent = "提问";
    $("#question").focus();
  }
}

/* ---------------- 检索追踪 ---------------- */
function renderTrace(trace, memoryInfo) {
  const box = $("#tab-trace");
  if (!trace) return;
  const filterText = Object.keys(trace.filter || {}).length
    ? JSON.stringify(trace.filter)
    : "（无结构化过滤）";
  const fused = (trace.fused || []).map((r) => `
    <div class="rank-item">
      <span class="r">${r.n}</span>
      <span class="nm">《${escapeHtml(r.title)}》 · ${escapeHtml(r.section)}</span>
      <span class="dv">${r.score == null ? "" : Number(r.score).toFixed(4)}</span>
    </div>`).join("") || '<p class="empty">无结果</p>';
  const vec = (trace.vector_route || []).map((r) => `
    <div class="rank-item">
      <span class="route-badge">向量</span>
      <span class="nm">《${escapeHtml(r.title)}》 · ${escapeHtml(r.section)}</span>
      <span class="dv">d=${r.distance == null ? "-" : Number(r.distance).toFixed(4)}</span>
    </div>`).join("") || '<p class="empty">向量通道无结果</p>';
  const fts = (trace.fulltext_route || []).map((r) => `
    <div class="rank-item">
      <span class="route-badge">全文</span>
      <span class="nm">《${escapeHtml(r.title)}》 · ${escapeHtml(r.section)}</span>
    </div>`).join("") || '<p class="empty">全文通道无结果</p>';

  const prep = (memoryInfo && (memoryInfo.memory_context || memoryInfo.prepared_context)) || "";
  box.innerHTML = `
    <div class="trace-block">
      <h5>检索方式</h5>
      <div class="code">${escapeHtml(trace.mode)}</div>
    </div>
    <div class="trace-block">
      <h5>全文关键词（IK 分词）</h5>
      <div class="code">${escapeHtml(trace.keywords)}</div>
    </div>
    <div class="trace-block">
      <h5>结构化过滤条件</h5>
      <div class="code">${escapeHtml(filterText)}</div>
    </div>
    <div class="trace-block">
      <h5>RRF 融合 Top-${(trace.fused || []).length}</h5>
      ${fused}
    </div>
    <div class="trace-block">
      <h5>向量通道（cosine KNN）</h5>
      ${vec}
    </div>
    <div class="trace-block">
      <h5>全文通道（MATCH ... AGAINST）</h5>
      ${fts}
    </div>
    <div class="trace-block">
      <h5>PowerContext 注入的上下文</h5>
      <div class="code">${prep ? escapeHtml(prep.slice(0, 900)) : "（本次未注入）"}</div>
    </div>`;
  switchTab("trace");
}

/* ---------------- 记忆 ---------------- */
const KIND_LABELS = {
  fact: "事实记忆",
  preference: "长期偏好",
  decision: "决策记忆",
  working_note: "会话摘要",
  WORKING_NOTE: "会话摘要",
};

function kindLabel(kind) {
  return KIND_LABELS[kind] || kind;
}

async function loadMemory() {
  const user = currentUser();
  try {
    const data = await api(`/api/memory?user_id=${encodeURIComponent(user)}`);
    const list = $("#mem-list");
    list.innerHTML = "";
    if (!data.available) {
      list.innerHTML = `<li class="empty">PowerContext 不可用：${escapeHtml(data.error || "")}</li>`;
      return;
    }
    if (!(data.memories || []).length) {
      list.innerHTML = '<li class="empty">还没有记忆。问一个问题，或手动添加一条。</li>';
      return;
    }
    const order = { preference: 0, fact: 1, decision: 2 };
    const memories = [...(data.memories || [])].sort(
      (a, b) => (order[a.kind] ?? 3) - (order[b.kind] ?? 3)
    );
    const seen = new Set();
    for (const m of memories) {
      const key = `${m.kind}\u0000${m.text}`;
      if (seen.has(key)) continue;
      seen.add(key);
      const li = document.createElement("li");
      li.className = m.kind === "preference" ? "mem pref" : "mem";
      li.innerHTML = `<div class="k">${escapeHtml(kindLabel(m.kind))}</div><p class="txt">${escapeHtml(m.text)}</p>`;
      list.appendChild(li);
    }
  } catch (err) {
    $("#mem-list").innerHTML = `<li class="empty">加载失败：${escapeHtml(err.message)}</li>`;
  }
}

function renderMemoryFromAsk(memoryInfo) {
  const box = $("#mem-list");
  if (!memoryInfo || !memoryInfo.enabled) return;
  box.innerHTML = "";
  for (const p of memoryInfo.preferences || []) {
    const li = document.createElement("li");
    li.className = "mem pref";
    li.innerHTML = `<div class="k">长期偏好 · 每轮生效</div><p class="txt">${escapeHtml(p.text)}</p>`;
    box.appendChild(li);
  }
  for (const hit of memoryInfo.hits || []) {
    const li = document.createElement("li");
    li.className = "mem";
    li.innerHTML = `
      <div class="k">命中 · ${escapeHtml(kindLabel(hit.kind))}</div>
      <p class="txt">${escapeHtml(hit.text)}</p>
      <div class="score">score ${hit.score == null ? "-" : Number(hit.score).toFixed(4)} · ${(hit.matched_by || []).join("/")}</div>`;
    box.appendChild(li);
  }
  for (const w of memoryInfo.written || []) {
    const li = document.createElement("li");
    li.className = "mem written";
    li.innerHTML = `<div class="k">本轮回写 · ${escapeHtml(kindLabel(w.kind))}</div><p class="txt">${escapeHtml(w.text)}</p>`;
    box.appendChild(li);
  }
  if (!box.children.length) {
    box.innerHTML = '<li class="empty">本轮没有记忆命中或回写。</li>';
  }
}

async function saveManualMemory() {
  const input = $("#mem-input");
  const text = input.value.trim();
  if (!text) return;
  try {
    await api("/api/memory", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: currentUser(), kind: "fact", text }),
    });
    input.value = "";
    loadMemory();
  } catch (err) {
    alert(`保存失败：${err.message}`);
  }
}

/* ---------------- 导入 ---------------- */
function switchTab(name) {
  $$(".tab[data-tab]").forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === name));
  $("#tab-trace").classList.toggle("hidden", name !== "trace");
  $("#tab-memory").classList.toggle("hidden", name !== "memory");
  if (name === "memory") loadMemory();
}

function switchImport(name) {
  state.importMode = name;
  $$(".tab[data-import]").forEach((tab) => tab.classList.toggle("active", tab.dataset.import === name));
  $("#pane-file").classList.toggle("hidden", name !== "file");
  $("#pane-text").classList.toggle("hidden", name !== "text");
}

async function doImport() {
  const hint = $("#import-hint");
  const btn = $("#do-import");
  btn.disabled = true;
  hint.textContent = "导入并生成向量中…";
  try {
    const meta = {
      type: $("#meta-type").value,
      year: $("#meta-year").value.trim(),
      tags: $("#meta-tags").value.trim(),
    };
    let result;
    if (state.importMode === "file") {
      if (!state.file) throw new Error("请先选择文件");
      const form = new FormData();
      form.append("file", state.file);
      form.append("type", meta.type);
      form.append("year", meta.year);
      form.append("tags", meta.tags);
      result = await api("/api/documents/upload", { method: "POST", body: form });
    } else {
      const title = $("#text-title").value.trim();
      const content = $("#text-content").value.trim();
      if (!title || !content) throw new Error("标题和正文都要填写");
      result = await api("/api/documents/text", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, content, type: meta.type, year: Number(meta.year) || null, tags: meta.tags }),
      });
    }
    hint.textContent = `《${result.title}》已切分为 ${result.chunks} 片 · ${result.memory || ""}`;
    state.file = null;
    $("#file-name").textContent = "";
    $("#text-title").value = "";
    $("#text-content").value = "";
    await loadDocs();
    await loadHealth();
    setTimeout(closeImport, 900);
  } catch (err) {
    hint.textContent = `导入失败：${err.message}`;
  } finally {
    btn.disabled = false;
  }
}

function openImport() { $("#import-modal").classList.remove("hidden"); }
function closeImport() { $("#import-modal").classList.add("hidden"); $("#import-hint").textContent = ""; }

/* ---------------- 事件绑定 ---------------- */
function bind() {
  $("#ask-btn").addEventListener("click", ask);
  $$(".chat-empty .samples button").forEach((btn) =>
    btn.addEventListener("click", () => {
      $("#question").value = btn.dataset.q || "";
      ask();
    })
  );
  $("#question").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      ask();
    }
  });
  $("#filter-type").addEventListener("change", renderDocs);
  $("#filter-year").addEventListener("change", renderDocs);
  $("#user-id").addEventListener("change", () => {
    localStorage.setItem("papermind.user", currentUser());
    state.memoryLoaded = true;
    loadMemory();
  });

  $$(".tab[data-tab]").forEach((tab) => tab.addEventListener("click", () => switchTab(tab.dataset.tab)));
  $$(".tab[data-import]").forEach((tab) => tab.addEventListener("click", () => switchImport(tab.dataset.import)));

  $("#open-import").addEventListener("click", openImport);
  $("#close-import").addEventListener("click", closeImport);
  $("#import-modal").addEventListener("click", (event) => {
    if (event.target.id === "import-modal") closeImport();
  });
  $("#do-import").addEventListener("click", doImport);
  $("#mem-save").addEventListener("click", saveManualMemory);
  $("#mem-input").addEventListener("keydown", (event) => {
    if (event.key === "Enter") saveManualMemory();
  });

  const fileInput = $("#file-input");
  fileInput.addEventListener("change", () => {
    state.file = fileInput.files[0] || null;
    $("#file-name").textContent = state.file ? state.file.name : "";
  });

  const zone = $("#drop-zone");
  ["dragenter", "dragover"].forEach((name) =>
    zone.addEventListener(name, (event) => {
      event.preventDefault();
      zone.classList.add("over");
    })
  );
  ["dragleave", "drop"].forEach((name) =>
    zone.addEventListener(name, (event) => {
      event.preventDefault();
      zone.classList.remove("over");
    })
  );
  zone.addEventListener("drop", (event) => {
    const file = event.dataTransfer.files[0];
    if (!file) return;
    state.file = file;
    $("#file-name").textContent = file.name;
  });
}

function boot() {
  const saved = localStorage.getItem("papermind.user");
  if (saved) $("#user-id").value = saved;
  bind();
  loadHealth();
  loadDocs();
  setInterval(loadHealth, 30000);
}

boot();

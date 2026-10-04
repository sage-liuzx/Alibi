// AI 侦探游戏 · 前端（纯 JS，无框架）
// 阶段 2：场景 + 人物 + 动画；搜证从"自由 grep"改为"点击场景物件"（顺带堵住信息泄漏）

// ---------------- 场景定义（纯前端展示数据，query 是点击后去查的关键词）----------------
const SCENES = [
  {
    id: "lobby", name: "🏢 大楼大厅",
    desc: "凌晨的大厅空无一人，前台的门禁终端还亮着幽幽蓝光。",
    hotspots: [
      { id: "badge",  label: "门禁终端",  x: 26, y: 64, query: "门禁" },
      { id: "pc",     label: "前台电脑",  x: 60, y: 68, query: "email" },
      { id: "board",  label: "公告栏",    x: 83, y: 42, query: "被裁" },
    ],
  },
  {
    id: "server", name: "🖥️ 服务器机房",
    desc: "机柜嗡嗡作响。门锁面板上，还留着凌晨的刷卡记录。",
    hotspots: [
      { id: "door", label: "门锁面板",   x: 20, y: 52, query: "B-2077" },
      { id: "rack", label: "服务器机柜", x: 47, y: 46, query: "svc_backup" },
      { id: "term", label: "运维终端",   x: 72, y: 60, query: "0104" },
      { id: "bin",  label: "废纸篓",     x: 87, y: 78, query: "删除" },
      { id: "log",  label: "值班记录",   x: 34, y: 78, query: "赌债" },
    ],
  },
  {
    id: "interrogation", name: "🚪 审讯室",
    desc: "四个人坐成一排。点谁，问谁。",
    suspects: true,
  },
];

const NAMES = ["Alex", "Bob", "Carol", "David"];
const ROLES = {
  Alex: "Helios 研发工程师",
  Bob: "前员工（已裁）",
  Carol: "IT 外包运维",
  David: "机房管理员",
};
const COLORS = { Alex: "#4a6fa5", Bob: "#8a5a3b", Carol: "#4f8a6b", David: "#a55a5a" };

let notebook = [];
let examined = {};        // hotspot id -> 是否已查看
let currentScene = "lobby";
let currentNpc = null;

// ---------------- 后端调用 ----------------
async function api(path, body) {
  const res = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  return res.json();
}

// ---------------- 初始化 ----------------
async function init() {
  const state = await api("/api/state");
  document.getElementById("case-title").textContent = state.case.title;
  document.getElementById("case-summary").textContent =
    state.case.summary + "　案发时间：" + state.case.time;
  notebook = state.notebook || [];
  renderTabs();
  renderScene(currentScene);
  renderNotebook();
}

function renderTabs() {
  const tabs = document.getElementById("scene-tabs");
  tabs.innerHTML = "";
  for (const s of SCENES) {
    const b = document.createElement("button");
    b.textContent = s.name;
    b.className = s.id === currentScene ? "active" : "";
    b.onclick = () => { currentScene = s.id; renderTabs(); renderScene(s.id); };
    tabs.appendChild(b);
  }
}

// ---------------- 场景渲染 ----------------
function renderScene(id) {
  const scene = SCENES.find((s) => s.id === id);
  const view = document.getElementById("scene-view");
  view.innerHTML = `<div class="scene-bg scene-${scene.id}">
      <div class="scene-desc">${scene.desc}</div>
    </div>`;
  const bg = view.querySelector(".scene-bg");

  if (scene.suspects) {
    const grid = document.createElement("div");
    grid.className = "suspect-grid";
    for (const name of NAMES) grid.appendChild(suspectCard(name));
    bg.appendChild(grid);
  } else {
    for (const h of scene.hotspots) {
      const btn = document.createElement("button");
      btn.className = "hotspot" + (examined[h.id] ? " done" : "");
      btn.style.left = h.x + "%";
      btn.style.top = h.y + "%";
      btn.textContent = h.label;
      btn.onclick = () => examine(h);
      bg.appendChild(btn);
    }
  }
}

function avatarSvg(name) {
  const color = COLORS[name] || "#666";
  return `<svg class="portrait" viewBox="0 0 100 100">
    <defs>
      <linearGradient id="g-${name}" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="${color}"/>
        <stop offset="1" stop-color="#10141a"/>
      </linearGradient>
    </defs>
    <rect width="100" height="100" rx="10" fill="url(#g-${name})"/>
    <circle cx="50" cy="38" r="17" fill="rgba(255,255,255,.88)"/>
    <path d="M18 96 Q50 60 82 96 Z" fill="rgba(255,255,255,.88)"/>
  </svg>`;
}

function suspectCard(name) {
  const card = document.createElement("div");
  card.className = "suspect";
  card.innerHTML = `
    ${avatarSvg(name)}
    <div class="name">${name}</div>
    <div class="role">${ROLES[name]}</div>
    <div class="actions">
      <button class="profile-btn">档案</button>
      <button class="talk">盘问</button>
      <button class="accuse">指认</button>
    </div>`;
  card.querySelector(".profile-btn").onclick = () => openProfile(name);
  card.querySelector(".talk").onclick = () => openDialogue(name);
  card.querySelector(".accuse").onclick = () => accuse(name);
  return card;
}

// ---------------- 搜证（点击物件）----------------
async function examine(hotspot) {
  const data = await api("/api/investigate", { keyword: hotspot.query });
  examined[hotspot.id] = true;
  notebook = data.notebook || [];
  renderScene(currentScene);
  renderNotebook();
  showFindings(hotspot.label, data.hits);
}

function showFindings(label, hits) {
  const box = document.getElementById("findings");
  if (!hits || hits.length === 0) {
    box.innerHTML = `<h3>🔍 ${label}</h3><p>没有发现有用的东西。</p>`;
  } else {
    box.innerHTML =
      `<h3>🔍 ${label} · 发现 ${hits.length} 条线索（已存入笔记本）</h3>` +
      hits.map((h) => `<p>· ${h}</p>`).join("");
  }
  box.classList.remove("hidden");
}

// ---------------- 笔记本 ----------------
function renderNotebook() {
  const list = document.getElementById("notebook-list");
  document.getElementById("notebook-count").textContent = `(${notebook.length})`;
  list.innerHTML = "";
  for (const line of notebook) {
    const li = document.createElement("li");
    li.textContent = line;
    list.appendChild(li);
  }
}

// ---------------- 盘问 ----------------
function openDialogue(name) {
  currentNpc = name;
  document.getElementById("dialogue-name").textContent = "盘问 · " + name;
  document.getElementById("dialogue-log").innerHTML = "";
  document.getElementById("dialogue").classList.remove("hidden");
  addLog("sys", `你坐在 ${name} 对面。开始提问吧。`);
  document.getElementById("dialogue-input").focus();
}

function closeDialogue() {
  document.getElementById("dialogue").classList.add("hidden");
  currentNpc = null;
}

function addLog(kind, text) {
  const log = document.getElementById("dialogue-log");
  const div = document.createElement("div");
  div.className = "msg " + kind;
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;
  div.appendChild(bubble);
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
  return div;
}

async function sendMessage() {
  const input = document.getElementById("dialogue-input");
  const text = input.value.trim();
  if (!text || !currentNpc) return;
  input.value = "";
  addLog("you", text);

  const typing = addLog("npc", "……");
  typing.classList.add("typing");

  const data = await api("/api/talk", { npc: currentNpc, message: text });
  typing.remove();

  if (data.error) { addLog("sys", "【错误】" + data.error); return; }

  if (data.gated && data.gated.length) {
    addLog("sys", "（你只是猜测，没有证据支撑，对方不为所动）");
  }
  if (data.pressure && data.pressure.length) {
    addLog("sys", `（你出示了证据：${data.pressure.join("、")}）`);
    const box = document.getElementById("dialogue-box");
    box.classList.remove("shake");
    void box.offsetWidth;   // 重置动画
    box.classList.add("shake");
  }
  addLog("npc", data.reply);
}

// ---------------- 指认 ----------------
async function accuse(name) {
  if (!confirm(`确定指认 ${name} 是凶手吗？指认后游戏结束。`)) return;
  const data = await api("/api/accuse", { npc: name });
  if (data.error) { alert(data.error); return; }
  document.getElementById("ending-title").textContent = data.win ? "🕵️ 真相大白" : "🔒 案件未破";
  document.getElementById("ending-text").textContent = data.ending;
  document.getElementById("ending").classList.remove("hidden");
}

// ---------------- 人物档案 ----------------
let currentProfileName = null;

async function openProfile(name) {
  const data = await api("/api/profile", { npc: name });
  if (data.error) { alert(data.error); return; }
  currentProfileName = name;
  const p = data.profile;
  document.getElementById("profile-name").textContent = `${p.name} · ${p.role}`;
  document.getElementById("profile-body").innerHTML =
    `<b>工卡：</b>${p.card}<br><b>邮箱：</b>${p.email}<br><br>${p.note}` +
    `<br><br><i>（这份档案已记入笔记本）</i>`;
  document.getElementById("profile").classList.remove("hidden");
  notebook = data.notebook || notebook;
  renderNotebook();
}

function closeProfile() {
  document.getElementById("profile").classList.add("hidden");
}

function talkFromProfile() {
  const name = currentProfileName;
  closeProfile();
  openDialogue(name);
}

// ---------------- 重新开始（要通知后端清空）----------------
async function restart() {
  await api("/api/reset", {});
  location.reload();
}

function showHelp() {
  document.getElementById("help").classList.remove("hidden");
}

init();

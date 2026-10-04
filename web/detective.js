// AI 侦探模式 · 前端（agent 当侦探，玩家当嫌疑人）

let ACTIONS = [];
let actionsLeft = 5;
let USED = new Set();
let busy = false;

async function api(path, body) {
  const res = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  return res.json();
}

async function init() {
  const data = await api("/api/detective/start", {});
  document.getElementById("brief").textContent = data.brief;
  ACTIONS = data.actions;
  actionsLeft = data.snapshot.actions_left;
  USED = new Set(data.snapshot.used_actions || []);
  renderActions();
}

// ---------------- 掩盖手段 ----------------
function renderActions() {
  const grids = [
    ["prep-actions", "prep-points"],
    ["session-actions", "session-points"],
  ];
  for (const [gridId, pointsId] of grids) {
    const grid = document.getElementById(gridId);
    if (!grid) continue;
    grid.innerHTML = "";
    for (const a of ACTIONS) {
      const used = USED.has(a.id);
      const card = document.createElement("button");
      card.className = "action-card" + (used ? " used" : "");
      card.disabled = actionsLeft <= 0 || used;
      card.innerHTML = `<b>${a.label}</b><span>${used ? "已使用" : a.desc}</span>`;
      card.onclick = () => useAction(a.id);
      grid.appendChild(card);
    }
    document.getElementById(pointsId).textContent = actionsLeft;
  }
}

async function useAction(id) {
  if (busy || actionsLeft <= 0) return;
  setBusy(true);
  const snap = await api("/api/detective/act", { action: id });
  setBusy(false);
  if (snap.error) { alert(snap.error); return; }
  actionsLeft = snap.actions_left;
  USED = new Set(snap.used_actions || []);
  renderActions();
  renderPrepLog(snap.timeline);
  if (snap.status === "finished") showEnding(snap.result);
}

function renderPrepLog(timeline) {
  const box = document.getElementById("prep-log");
  if (!box) return;
  const acts = (timeline || []).filter((e) => e.who === "action");
  box.innerHTML = acts.map((e) => `<p>✔ ${e.text}</p>`).join("");
}

// ---------------- 审讯 ----------------
async function beginInterrogation() {
  document.getElementById("prep").classList.add("hidden");
  document.getElementById("session").classList.remove("hidden");
  setBusy(true);
  const snap = await api("/api/detective/advance", {});
  setBusy(false);
  handleSnapshot(snap);
}

async function sendAnswer() {
  const input = document.getElementById("answer-input");
  const text = input.value.trim();
  if (!text || busy) return;
  input.value = "";
  document.getElementById("answer-bar").classList.add("hidden");
  setBusy(true);
  const snap = await api("/api/detective/answer", { text });
  setBusy(false);
  handleSnapshot(snap);
}

function handleSnapshot(snap) {
  renderTimeline(snap.timeline);
  actionsLeft = snap.actions_left;
  USED = new Set(snap.used_actions || []);
  renderActions();

  if (snap.status === "finished") { showEnding(snap.result); return; }

  if (snap.status === "waiting") {
    document.getElementById("continue-bar").classList.add("hidden");
    document.getElementById("question").textContent = "侦探：" + snap.question;
    document.getElementById("answer-bar").classList.remove("hidden");
    document.getElementById("answer-input").focus();
    return;
  }

  // status === "ready"：侦探刚做完一个动作，停下等你决定
  document.getElementById("answer-bar").classList.add("hidden");
  document.getElementById("continue-bar").classList.remove("hidden");
}

async function continueDetective() {
  if (busy) return;
  document.getElementById("continue-bar").classList.add("hidden");
  setBusy(true);
  const snap = await api("/api/detective/advance", {});
  setBusy(false);
  handleSnapshot(snap);
}

function renderTimeline(timeline) {
  const box = document.getElementById("timeline");
  box.innerHTML = "";
  for (const ev of timeline) {
    const div = document.createElement("div");
    div.className = "det-event det-" + ev.who;
    div.textContent = ev.text;
    box.appendChild(div);
  }
  box.scrollTop = box.scrollHeight;
}

function setBusy(value) {
  busy = value;
  document.getElementById("waiting").classList.toggle("hidden", !value);
}

// ---------------- 结局 ----------------
function showEnding(result) {
  if (!result) return;
  document.getElementById("ending-title").textContent = result.title;
  document.getElementById("ending-text").textContent = result.text;
  document.getElementById("ending").classList.remove("hidden");
}

async function restart() {
  await api("/api/reset", {});
  location.reload();
}

init();

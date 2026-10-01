const $ = id => document.getElementById(id);
const state = { choices: [], turn: 0, log: [], title: "" };
let busyTurn = false;

async function refreshStatus() {
  try {
    const r = await fetch("/api/status");
    const j = await r.json();
    $("statusDot").className = "dot " + (j.has_key ? "ok" : "no");
    $("statusText").textContent = j.has_key ? `key ✓ · ${j.model}` : "no key — open Settings";
  } catch { $("statusText").textContent = "offline"; }
}

function clampHealth(h) {
  const n = Number(h);
  if (!Number.isFinite(n)) return 100;
  return Math.max(0, Math.min(100, n));
}

function renderCommon(d) {
  state.turn = d.turn ?? state.turn;
  $("gTitle").textContent = state.title || d.title || "Adventure";
  $("gMeta").textContent = `Turn ${state.turn}`;
  $("pTurn").textContent = `Turn ${state.turn}`;
  $("pLoc").textContent = `📍 ${d.state?.location || "—"}`;
  const hp = d.state?.health ?? "—";
  $("pHealth").textContent = `❤️ ${hp}`;
  $("healthFill").style.width = `${clampHealth(d.state?.health ?? 100)}%`;
  $("invList").innerHTML = (d.state?.inventory?.length ? d.state.inventory.map(i => `<span>${escapeHtml(i)}</span>`).join("") : "— (empty)");
  $("flagList").textContent = "Flags: " + ((d.state?.flags?.length ? d.state.flags.join(", ") : "—"));
  if (d.event) $("eventText").textContent = d.event;
  if (d.consequence) $("conseqText").textContent = d.consequence;
  renderCodex(d.world_state);
  state.choices = d.choices || [];
  renderChoices();
}

function renderCodex(ws) {
  const el = $("codexBody");
  if (!el) return;
  if (!ws || typeof ws !== "object") { el.textContent = "Codex empty — the tale keeps no notes yet."; return; }
  const chars = (ws.characters || []).map(c => typeof c === "object" ? `${c.name}${c.note ? ` (${c.note})` : ""}` : String(c));
  const locs = ws.locations || [], items = ws.items || [], threads = ws.open_threads || [];
  el.innerHTML =
    `<div><b>Turn:</b> ${escapeHtml(ws.turn ?? "?")}</div>` +
    `<div><b>Characters:</b> ${escapeHtml(chars.join(", ") || "—")}</div>` +
    `<div><b>Locations:</b> ${escapeHtml(locs.join(", ") || "—")}</div>` +
    `<div><b>Items:</b> ${escapeHtml(items.join(", ") || "—")}</div>` +
    `<div><b>Open threads:</b> ${escapeHtml(threads.join(" · ") || "—")}</div>`;
}

function renderChoices() {
  const box = $("choices"); box.innerHTML = "";
  state.choices.forEach((c, i) => {
    const b = document.createElement("button");
    b.textContent = `${i + 1}. ${c}`;
    b.disabled = busyTurn;
    b.onclick = () => doChoose(i);
    box.appendChild(b);
  });
}

function escapeHtml(s) { return String(s).replace(/[&<>"']/g, m => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m])); }

function pushLog(turn, label, body) {
  state.log.push({ turn, label, body });
  const el = document.createElement("div");
  el.innerHTML = `<b>T${turn} — ${escapeHtml(label)}</b><br>${escapeHtml(body)}`;
  $("storyLog").appendChild(el);
  $("storyLog").scrollTop = $("storyLog").scrollHeight;
}

function showGame(v) { $("gameCard").classList.toggle("hidden", !v); $("setupCard").classList.toggle("hidden", v); }
function showFinale(title, ep) {
  $("finaleCard").classList.remove("hidden");
  $("endTitle").textContent = title; $("endEpilogue").textContent = ep;
  $("finaleCard").scrollIntoView({ behavior: "smooth" });
}
function err(msg) { $("gameErr").textContent = msg || ""; }
function setBusy(b) { busyTurn = b; $("customBtn").disabled = b; renderChoices(); }

async function doStart() {
  if (busyTurn) return;
  err(""); $("setupErr").textContent = "";
  const body = { genre: $("genre").value, style: $("style").value, setting: $("setting").value.trim(), character: $("character").value.trim() };
  if (!body.setting || !body.character) { $("setupErr").textContent = "Setting and character are required."; return; }
  $("startBtn").disabled = true; $("startBtn").textContent = "Conjuring…";
  try {
    const r = await fetch("/api/start", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || "Start failed");
    state.title = j.title; state.log = []; $("storyLog").innerHTML = "";
    $("finaleCard").classList.add("hidden");
    showGame(true);
    renderCommon({ ...j, consequence: "" });
    $("conseqText").textContent = "The tale begins. Choose wisely.";
    pushLog(0, "Opening", j.opening || j.event);
  } catch (e) { $("setupErr").textContent = e.message; }
  finally { $("startBtn").disabled = false; $("startBtn").textContent = "Begin Adventure"; }
}

async function doChoose(i) {
  if (busyTurn) return;
  err("");
  setBusy(true);
  try {
    const r = await fetch("/api/choose", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ choice_index: i }) });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || "Choice failed");
    pushLog(j.turn, `Choice: ${j.picked || state.choices[i]}`, `${j.consequence}\n\n${j.event}`);
    renderCommon(j);
    if (j.ending) showFinale(j.ending.title, j.ending.epilogue);
  } catch (e) { err(e.message); }
  finally { setBusy(false); }
}

async function doCustom() {
  if (busyTurn) return;
  const a = $("customInput").value.trim();
  if (!a) { err("Custom action must not be empty."); return; }
  if (a.length > 500) { err("Custom action must be ≤ 500 characters."); return; }
  err(""); setBusy(true);
  try {
    const r = await fetch("/api/custom", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: a }) });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || "Custom action failed");
    pushLog(j.turn, `You: ${a}`, `${j.consequence}\n\n${j.event}`);
    $("customInput").value = "";
    renderCommon(j);
    if (j.ending) showFinale(j.ending.title, j.ending.epilogue);
  } catch (e) { err(e.message); }
  finally { setBusy(false); }
}

function downloadMD(md, title) {
  const blob = new Blob([md], { type: "text/markdown" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = (title || "story").replace(/[^\w\-]+/g, "_").slice(0, 60) + ".md";
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}
async function doExport() {
  const r = await fetch("/api/export"); const j = await r.json();
  if (!r.ok) { err(j.error); return; }
  downloadMD(j.markdown, j.title);
}
async function doCopy() {
  try {
    const r = await fetch("/api/export"); const j = await r.json();
    if (!r.ok) { err(j.error); return; }
    await navigator.clipboard.writeText(j.markdown);
    err("Copied to clipboard ✓"); setTimeout(() => err(""), 2000);
  } catch {
    err("Copy failed in this browser.");
  }
}
async function doRestart() {
  await fetch("/api/restart", { method: "POST" });
  $("finaleCard").classList.add("hidden"); showGame(false); state.title = "";
}

// FIX: restore() was previously nested inside the saveKeyBtn handler so it
// never ran on page load. Moved to top level.
async function restore() {
  try {
    const r = await fetch("/api/story");
    if (!r.ok) return;
    const j = await r.json();
    if (!j.active && !j.title) return; // no story yet — stay on the setup page
    state.title = j.title || "";
    state.log = []; $("storyLog").innerHTML = "";
    (j.log || []).forEach(e => pushLog(e.turn, e.type === "opening" ? "Opening" : (e.text || "Turn"), [e.consequence, e.event].filter(Boolean).join("\n\n") || e.text || ""));
    showGame(true);
    renderCommon({ ...j, consequence: j.consequence || "" });
    if (j.ending) showFinale(j.ending.title, j.ending.epilogue);
  } catch {}
}

// settings modal — frontend NEVER stores/sends keys except POST /api/key on save
function openSettings() { $("settingsModal").classList.remove("hidden"); $("keyMsg").textContent = ""; $("keyInput").focus(); }
function closeSettings() { $("settingsModal").classList.add("hidden"); $("keyInput").value = ""; }
$("settingsBtn").onclick = openSettings;
$("closeSettings").onclick = closeSettings;
$("settingsModal").addEventListener("click", (e) => { if (e.target === $("settingsModal")) closeSettings(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("settingsModal").classList.contains("hidden")) closeSettings(); });
$("keyInput").addEventListener("keydown", (e) => { if (e.key === "Enter") $("saveKeyBtn").click(); });
$("saveKeyBtn").onclick = async () => {
  const k = $("keyInput").value.trim();
  $("keyMsg").textContent = "Verifying…";
  const r = await fetch("/api/key", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key: k }) });
  const j = await r.json();
  $("keyMsg").textContent = r.ok ? "Key verified & stored (server memory only) ✓" : ("✗ " + (j.error || "failed"));
  $("keyInput").value = "";
  refreshStatus();
};
$("delKeyBtn").onclick = async () => { await fetch("/api/key", { method: "DELETE" }); $("keyMsg").textContent = "Server key cleared."; refreshStatus(); };

$("startBtn").onclick = doStart;
$("customBtn").onclick = doCustom;
$("customInput").addEventListener("keydown", e => { if (e.key === "Enter") doCustom(); });
$("exportBtn").onclick = doExport; $("exportBtn2").onclick = doExport;
$("copyBtn").onclick = doCopy;
$("restartBtn").onclick = doRestart;
$("againBtn").onclick = doRestart;
refreshStatus();
restore();

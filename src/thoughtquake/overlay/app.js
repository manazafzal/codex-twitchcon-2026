/* The stream owns game decisions; this module only renders events. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const palette = ["#E69F00", "#56B4E9", "#009E73", "#F0E442", "#D55E00", "#CC79A7", "#0072B2"];
  const styles = ["solid", "dashed", "dotted"];
  const svgNS = "http://www.w3.org/2000/svg";
  let concepts = new Map([
    ["ocean", {label: "Ocean", color_index: 0}],
    ["space", {label: "Space", color_index: 1}],
    ["jazz", {label: "Jazz", color_index: 2}]
  ]);
  let currentMode = {mode: "war", panel: "main", answer: -1, phase: "generating"};
  let currentTokens = [], history = [], pushes = [], readouts = [];
  let activeFactions = ["ocean", "space", "jazz"];
  let wordQueue = [], carry = null, socket = null, captionTimer = null;
  let fixture = Boolean(window.THOUGHTQUAKE_FIXTURE);
  let retry = 500;
  let overlayConnected = true, twitchState = "connected";
  function renderConnection() {
    $("connection").hidden = overlayConnected && twitchState === "connected";
    $("connection").textContent = ["revoked", "auth_required"].includes(twitchState) ? "AUTH REQUIRED" : "RECONNECTING";
  }
  const hiddenNames = () => currentMode.mode === "telepathy" && currentMode.phase !== "reveal";
  const color = (f) => f && concepts.has(f) ? palette[concepts.get(f).color_index % palette.length] : "#F5F7FA";
  const label = (f) => f === "Neutral" ? "Neutral" : concepts.get(f)?.label || f;
  function scale() {
    const factor = Math.min(innerWidth / 1920, innerHeight / 1080);
    $("stage").style.transform = `scale(${factor})`;
    $("stage").style.left = `${(innerWidth - 1920 * factor) / 2}px`;
    $("stage").style.top = `${(innerHeight - 1080 * factor) / 2}px`;
  }
  addEventListener("resize", scale); scale();
  if (new URLSearchParams(location.search).get("bg") === "transparent") {
    document.body.classList.add("transparent");
    document.documentElement.style.background = "transparent";
  }
  function word(text, faction, target) {
    const span = document.createElement("span");
    span.className = "word";
    span.textContent = text;
    span.style.color = hiddenNames() ? "#F5F7FA" : color(faction);
    span.style.textDecorationStyle = styles[(concepts.get(faction)?.color_index || 0) % styles.length];
    if (!faction || hiddenNames()) span.style.textDecorationLine = "none";
    target.append(span);
    $("thinking").hidden = true;
  }
  function target() { return currentMode.mode === "attack" ? $(`attack-${currentMode.panel}`) : $("answer"); }
  function flushCarry() { if (carry) { wordQueue.push(carry); carry = null; } }
  function enqueueToken(event, immediate = false) {
    // Token fragments are joined before display so a byte/BPE token never becomes a fake word.
    const parts = event.text.match(/\s+|\S+/g) || [];
    for (const part of parts) {
      if (/^\s+$/.test(part)) {
        if (carry) { carry.text += part; flushCarry(); }
        else wordQueue.push({text: part, faction: event.color, target: target()});
      } else if (carry) carry.text += part;
      else carry = {text: part, faction: event.color, target: target()};
    }
    if (immediate) { flushCarry(); while (wordQueue.length) { const w = wordQueue.shift(); word(w.text, w.faction, w.target); } }
  }
  setInterval(() => {
    if (wordQueue.length) { const w = wordQueue.shift(); word(w.text, w.faction, w.target); }
  }, 90);
  let carryTimer;
  function queue(event) {
    clearTimeout(carryTimer);
    enqueueToken(event, fixture);
    // Flush a final word when the model pauses or ends its answer.
    carryTimer = setTimeout(flushCarry, 160);
  }
  function renderHistory() {
    $("history").replaceChildren();
    for (const item of history.slice(-3).reverse()) {
      const card = document.createElement("div"); card.className = "history-card";
      const heading = document.createElement("b"); heading.textContent = `Answer ${item.mode.answer + 1}`;
      card.append(heading, document.createTextNode(item.tokens.map(t => t.text).join("")));
      card.style.borderColor = color(item.tokens.find(t => t.color)?.color);
      $("history").append(card);
    }
  }
  function mode(event, restoring = false) {
    const changed = event.mode !== currentMode.mode;
    const newAnswer = event.answer !== currentMode.answer || event.panel !== currentMode.panel || changed;
    if (newAnswer && ["armed", "generating"].includes(event.phase)) {
      flushCarry();
      // Finish buffered words before archiving the previous answer.
      while (wordQueue.length) { const w = wordQueue.shift(); word(w.text, w.faction, w.target); }
      if (currentTokens.length && !restoring) history.push({mode: currentMode, tokens: currentTokens});
      history = history.slice(-3); currentTokens = [];
      $("answer").replaceChildren();
      if (event.mode !== "attack" || event.panel === "off") {
        $("attack-off").replaceChildren(); $("attack-on").replaceChildren();
      }
      $("thinking").hidden = false;
      if (event.mode === "telepathy") { readouts = []; chart(); }
    }
    currentMode = event;
    $("stage").dataset.mode = event.mode;
    $("stage").dataset.phase = event.phase;
    $("round-label").textContent = `Answer ${event.answer + 1} · ${event.prompt}`;
    $("immune").textContent = `IMMUNE: ${event.immune ? "ON" : "OFF"}`;
    $("colour-label").textContent = event.colour_source === "readout" ? "/ MIND-READER COLOURS" : "/ TERRITORY";
    $("answer").hidden = event.mode === "attack";
    $("comparison").hidden = event.mode !== "attack";
    $("telepathy").hidden = event.mode !== "telepathy";
    $("countdown").textContent = `${Math.ceil(event.remaining ?? 30)} s`;
    $("reveal").textContent = event.reveal ? `Reveal: ${label(event.reveal)} · Mind-Reader: ${label(event.probe_top) || "unavailable"} · First correct: ${event.winner || "no winner"}${event.probe_accuracy == null ? "" : ` · Real-model round accuracy: ${Math.round(event.probe_accuracy * 100)} %`}` : "";
    $("scoreboard").textContent = event.scoreboard?.length ? event.scoreboard.map(([user, points]) => `${user}: ${points}`).join(" · ") : "No points yet";
    if (changed && !fixture) {
      clearTimeout(captionTimer); $("mode-caption").hidden = false;
      $("mode-caption").textContent = `ROUND: ${event.mode.toUpperCase()}`;
      captionTimer = setTimeout(() => { $("mode-caption").hidden = true; }, 1500);
    }
    renderHistory(); chart();
  }
  function tick(event) {
    const active = Object.entries(event.shares);
    activeFactions = active.filter(([f, share]) => f !== "Neutral" && share > 0).map(([f]) => f);
    const existing = new Map([...$("shares").children].map(node => [node.dataset.faction, node]));
    for (const [f, share] of active) {
      let node = existing.get(f);
      if (!node) { node = document.createElement("div"); node.className = "share"; node.dataset.faction = f; node.append(document.createElement("span")); $("shares").append(node); }
      node.style.width = `${share * 100}%`;
      node.style.background = f === "Neutral" ? "#3C475B" : color(f);
      node.classList.toggle("neutral", f === "Neutral");
      node.firstChild.textContent = `${hiddenNames() ? "?" : label(f).toUpperCase()} ${Math.round(share * 100)} %`;
      node.firstChild.hidden = share < .12;
      existing.delete(f);
    }
    for (const node of existing.values()) node.remove();
    $("legend").replaceChildren();
    for (const [f] of active.filter(([f]) => f !== "Neutral")) {
      const span = document.createElement("span"), dot = document.createElement("i"); dot.style.background = color(f);
      span.append(dot, document.createTextNode(hiddenNames() ? "?" : `Team ${label(f)}`)); $("legend").append(span);
    }
  }
  function chart() {
    const blind = currentMode.mode === "telepathy" && currentMode.phase !== "reveal";
    $("blind-readout").hidden = !blind;
    const latest = readouts.at(-1) || {};
    ["A", "B", "C"].forEach((name, index) => {
      $("candidate-" + (index + 1)).style.width = `${Math.max(0, Math.min(1, latest[name] || 0)) * 100}%`;
    });
    $("chart").replaceChildren();
    const factions = currentMode.mode === "telepathy" ? ["A", "B", "C"] : activeFactions.slice(0, 3);
    const cumulative = readouts.map(() => 0);
    for (const f of factions) {
      const base = [...cumulative];
      const heights = readouts.map((row) => {
        const total = factions.reduce((sum, name) => sum + Math.max(0, row[name] || 0), 0);
        return total ? Math.max(0, row[f] || 0) / total * 100 : 0;
      });
      heights.forEach((height, i) => { cumulative[i] += height; });
      if (!readouts.length) continue;
      const x = i => 12 + i / 59 * 922;
      const upper = cumulative.map((y, i) => `${x(i)},${108 - y}`);
      const lower = base.map((y, i) => `${x(i)},${108 - y}`).reverse();
      const area = document.createElementNS(svgNS, "polygon"); area.setAttribute("points", [...upper, ...lower].join(" "));
      area.setAttribute("fill", color(f)); area.setAttribute("opacity", ".7"); $("chart").append(area);
    }
    const line = document.createElementNS(svgNS, "line");
    for (const [key, value] of Object.entries({x1: 934, x2: 934, y1: 0, y2: 112, stroke: "#F5F7FA", "stroke-width": 2})) line.setAttribute(key, value);
    $("chart").append(line);
  }
  function renderPushes() {
    $("pushes").replaceChildren();
    for (const event of pushes.slice(-5).reverse()) {
      const item = document.createElement("li"), user = document.createElement("span"); user.className = "user";
      user.textContent = `${event.user} → `;
      const faction = document.createElement("span"); faction.style.color = color(event.faction);
      faction.textContent = hiddenNames() ? "?" : label(event.faction); item.append(user, faction); $("pushes").append(item);
    }
  }
  const handlers = {
    badge(event) {
      // Synthetic chatters always retain the mandatory SIMULATED ×N badge.
      const simulated = /^SIMULATED ×\d+$/.test(event.label);
      $("source").textContent = simulated ? `SIMULATED ×${event.label.split("×")[1]}` : event.label;
      $("source").className = `chip ${simulated ? "simulated" : event.label.toLowerCase()}`;
      $("sim-source").hidden = !event.simulated_users;
      $("sim-source").textContent = `SIMULATED ×${event.simulated_users || 0}`;
      $("quality").hidden = !event.quality; $("quality").textContent = event.quality || "";
    },
    guess(event) { /* The director adjudicates guesses; rendering never awards points. */ },
    control(event) { /* Only the resulting immune event changes the display. */ },
    immune(event) {
      currentMode.immune = event.enabled;
      $("immune").textContent = `IMMUNE: ${event.enabled ? "ON" : "OFF"}`;
      $("neutralised").hidden = !event.enabled;
    },
    round(event) {
      if (event.phase === "end" || event.phase === "reveal") { flushCarry(); $("thinking").hidden = true; }
    },
    connection(event) {
      if (event.service !== "twitch") return;
      twitchState = event.state; renderConnection();
    },
    push(event) { pushes.push(event); pushes = pushes.slice(-5); renderPushes(); },
    tick,
    token(event) { currentTokens.push(event); queue(event); readouts.push(event.readout.scores); readouts = readouts.slice(-60); chart(); },
    mode,
    tamper(event) { $("neutralised").textContent = `NEUTRALISED ${Math.round(event.neutralised * 100)} %`; $("neutralised").hidden = !currentMode.immune; $("tamper").hidden = !event.concepts.length; $("tamper").textContent = `TAMPERING DETECTED: ${hiddenNames() ? "?" : event.concepts.join(", ")}`; },
    snapshot(event) {
      clearTimeout(carryTimer); carry = null; wordQueue = [];
      const state = event.state;
      concepts = new Map(state.concepts.map(c => [c.id, c]));
      twitchState = state.connections?.twitch || "connected"; renderConnection();
      currentTokens = []; history = state.history; pushes = state.pushes; readouts = state.readouts;
      mode(state.mode, true); if (state.immune) handlers.immune(state.immune); handlers.badge(state.badge); tick(state.tick); handlers.tamper(state.tamper);
      $("answer").replaceChildren(); $("attack-off").replaceChildren(); $("attack-on").replaceChildren();
      if (state.mode.mode === "attack") {
        for (const panel of ["off", "on"]) for (const token of state.panels[panel]) word(token.text, token.color, $(`attack-${panel}`));
      } else for (const token of state.tokens) word(token.text, token.color, $("answer"));
      currentTokens = state.tokens; renderHistory(); renderPushes(); chart();
    }
  };
  function dispatch(event) { const handler = handlers[event.kind]; if (handler) handler(event); }
  window.ThoughtquakeOverlay = {dispatch, handlers};
  function connect() {
    socket = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
    socket.onopen = () => { retry = 500; overlayConnected = true; renderConnection(); };
    socket.onmessage = message => { try { dispatch(JSON.parse(message.data)); } catch (error) { console.error("Invalid event", error); } };
    socket.onerror = () => socket.close();
    socket.onclose = () => { overlayConnected = false; renderConnection(); setTimeout(connect, retry); retry = Math.min(retry * 2, 10000); };
  }
  if (fixture) { for (const event of window.THOUGHTQUAKE_FIXTURE) dispatch(event); flushCarry(); }
  else connect();
})();

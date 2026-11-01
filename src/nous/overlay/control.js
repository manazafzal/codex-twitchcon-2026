(() => {
  "use strict";
  let immune = false;
  const status = document.getElementById("status");
  async function command(path, body) {
    try {
      const headers = {"Content-Type": "application/json"};
      const token = document.getElementById("token").value;
      if(token) headers.Authorization = `Bearer ${token}`;
      const result = await fetch(`/api/${path}`, {method: "POST", headers, body: JSON.stringify(body)});
      if (!result.ok) throw new Error(await result.text());
      if (path === "immune") immune = body.enabled;
      status.textContent = "Control accepted. Round changes apply between answers.";
    } catch (error) { status.textContent = error.message; }
  }
  const initial = location.hash.slice(1); history.replaceState(null, '', location.pathname);
  if(initial) document.getElementById("token").value = initial;
  fetch('/api/welcome').then(r=>{if(r.ok){document.getElementById('token-entry').hidden=true;document.getElementById('control-help').textContent='Your controls are ready. Start a round, or turn defence on.';status.textContent='Ready to play.';}}).catch(()=>{});
  document.getElementById('round').onclick=()=>command('round',{});
  document.querySelectorAll("[data-mode]").forEach(button => button.addEventListener("click", () => command("mode", {mode: button.dataset.mode})));
  document.getElementById("immune-on").onclick = () => command("immune", {enabled: true});
  document.getElementById("immune-off").onclick = () => command("immune", {enabled: false});
  async function toggle() {
    try {
      const state = await (await fetch("/api/state")).json();
      immune = state.immune_requested ?? state.immune?.enabled ?? false;
      await command("immune", {enabled: !immune});
    } catch (error) { status.textContent = error.message; }
  }
  addEventListener("keydown", event => {
    if (event.key.toLowerCase() === "r" && !["INPUT", "TEXTAREA"].includes(event.target.tagName) && !event.repeat) {
      event.preventDefault(); command('round',{});
    }
    if (event.key.toLowerCase() === "i" && !["INPUT", "TEXTAREA"].includes(event.target.tagName) && !event.repeat) {
      event.preventDefault(); toggle();
    }
  });
})();

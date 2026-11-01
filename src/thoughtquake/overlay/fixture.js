/* Canned rendering input, not measured model results. */
window.THOUGHTQUAKE_FIXTURE = [
  {kind: "badge", label: "SIMULATED ×40", quality: "TINY MODEL / CI"},
  {kind: "mode", mode: "war", immune: false, prompt: "Explain how to make tea.", answer: 6, panel: "main", phase: "generating", colour_source: "applied"},
  {kind: "tick", shares: {ocean: .54, space: .31, Neutral: .15}, beta: 1.1, top_pushers: [], t: 0},
  {kind: "push", user: "sim_014", faction: "ocean", source: "SIMULATED", t: 0},
  {kind: "push", user: "sim_027", faction: "space", source: "SIMULATED", t: 0},
  {kind: "push", user: "sim_008", faction: "ocean", source: "SIMULATED", t: 0},
  {kind: "push", user: "sim_031", faction: "space", source: "SIMULATED", t: 0},
  {kind: "push", user: "sim_006", faction: "ocean", source: "SIMULATED", t: 0}
];
for (let i = 0; i < 60; i++) {
  window.THOUGHTQUAKE_FIXTURE.push({kind: "token", i, text: "", applied: "ocean", color: "ocean", readout: {scores: {ocean: .55 + .12 * Math.sin(i / 8), space: .35 - .1 * Math.sin(i / 8)}, top: "ocean", margin: .2}});
}
window.THOUGHTQUAKE_FIXTURE.push({kind: "token", i: 60, text: "Let the water settle, like a quiet tide.\nWarm the cup, add your tea, and let it steep.\nA little patience makes an ordinary moment\nfeel like a small shore of calm.", applied: "ocean", color: "ocean", readout: {scores: {ocean: .68, space: .24}, top: "ocean", margin: .44}});

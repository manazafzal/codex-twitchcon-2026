/* Development-only recorded input. Every numeric signal is a captured backend measurement. */
(() => {
const data=window.THOUGHTQUAKE_TRACES, ui=window.ThoughtquakeOverlay;
const params=new URLSearchParams(location.search), scene=params.get('scene')||'war', backend=params.get('backend')||'mock';
window.THOUGHTQUAKE_FIXTURE=data[backend][scene];
let timeline=[],cursor=0;
function sceneEvents(name){const events=data[backend][name];let at=0;return events.map(event=>{if(event.kind==='token')at+=.12;else if(event.kind==='mode')at+=1.8;return {at,event};});}
function load(name){timeline=sceneEvents(name);cursor=0;}
const original=ui.step;
ui.step=dt=>{const atlas=window.ThoughtquakeAtlas,draw=atlas.draw;atlas.draw=()=>{};try{const end=ui.stats().time+dt;while(cursor<timeline.length&&timeline[cursor].at<=end){const item=timeline[cursor++];const now=ui.stats().time;original(Math.max(0,item.at-now));ui.dispatch(item.event);}original(Math.max(0,end-ui.stats().time));}finally{atlas.draw=draw;}atlas.draw();};
ui.fixture={scene,backend,provenance:data.provenance[backend],duration:20};
load(scene);
})();

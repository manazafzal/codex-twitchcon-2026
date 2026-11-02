(() => {
"use strict";
const $ = id => document.getElementById(id);
const params = new URLSearchParams(location.search), manual = params.has('manual');
const atlas = window.NousAtlas, palette = ['#5B8CFF','#F2C340','#2FC79A','#F0604A','#E877A6','#7CD0EE','#A685E6'];
let time=0, jobs=[], queue=[], words=[], rows=[], catalog=[], mode={}, history=[], socket, generation=0, nextWord=0, captionBorn=-10, lastTick=null, shareTween=null, currentShares=null, overlayConnected=true, twitchState='connected', engineState='connected', mvpVersion=0, deadline=null, revealVersion=0, answerParts=[], answerPushed=false, currentTarget=null;
const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
const names=new Map(), colours=new Map();
const roundLabels={war:'TEAM ROUND',attack:'DEFENCE CHALLENGE',telepathy:'GUESS THE THOUGHT'};
const label = id => names.get(id) || String(/^(?:[a-f0-9]{16}|voc\d{3})$/.test(id)?'Hidden thought':id==='Neutral'?'No team':id || 'No team').replaceAll('_',' ').toUpperCase();
function colour(id){if(!colours.has(id))colours.set(id,palette[colours.size%palette.length]);return colours.get(id);}
function later(fn,seconds){jobs.push({at:time+seconds,fn});}
function renderConnection(){$('connection').hidden=overlayConnected&&twitchState==='connected'&&engineState==='connected';text('connection',['revoked','auth_required'].includes(twitchState)?'SIGN IN AGAIN':engineState==='error'?'AI RESTARTING':'RECONNECTING');}
function text(id,value){$(id).textContent=value;}
function resize(){const s=Math.min(innerWidth/1920,innerHeight/1080);$('stage').style.transform=`scale(${s})`;}
addEventListener('resize',resize);resize();document.body.classList.toggle('transparent',params.get('bg')==='transparent');
// Only text nodes and local formatting elements: model text never becomes HTML.
function markdown(target,parts,animate=false){
 const raw=parts.map(p=>p.text).join('');let cursor=0,partIndex=0,boundary=parts[0]?.text.length||0;
 let bold=false,italic=false,code=false;target.replaceChildren();const spans=[];
 const special=/\\.|\*\*|__|`{1,3}|\*|_|!?(\[[^\]\n]*\])\([^\n)]*\)|^(?:#{1,6}\s+|>\s+|[-+*]\s+|\d+\.\s+)/gm;
 function append(value,index){
  if(!value)return;
  let offset=0;while(offset<value.length){
  while(partIndex<parts.length-1&&index+offset>=boundary){partIndex++;boundary+=parts[partIndex].text.length;}
  const span=document.createElement('span');const length=Math.max(1,Math.min(value.length-offset,boundary-index-offset));span.textContent=value.slice(offset,offset+length);offset+=length;span.dataset.born=parts[partIndex]?.born??time;
  let parent=target;if(bold){const node=document.createElement('strong');parent.append(node);parent=node;}if(italic){const node=document.createElement('em');parent.append(node);parent=node;}if(code){const node=document.createElement('code');parent.append(node);parent=node;}
  parent.append(span);if(animate){span.style.opacity=reduced?'1':Math.min(1,(time-Number(span.dataset.born))/.12);spans.push(span);}
  }
 }
 for(const match of raw.matchAll(special)){
  append(raw.slice(cursor,match.index),cursor);const mark=match[0];
  if(mark.startsWith('\\'))append(mark.slice(1),match.index);
  else if(mark==='**'||mark==='__'){if(code)append(mark,match.index);else bold=!bold;}
  else if(mark==='*'||mark==='_'){if(code)append(mark,match.index);else italic=!italic;}
  else if(mark.startsWith('`'))code=!code;
  else if(match[1])append(match[1].slice(1,-1),match.index);
  else if(/^[-+*]\s/.test(mark)||/^\d+\.\s/.test(mark))append('• ',match.index);
  cursor=match.index+mark.length;
 }
 append(raw.slice(cursor),cursor);return spans;
}
function fitAnswer(reset=false){
 const answer=$('answer');let upper=reset?56:Math.round(parseFloat(getComputedStyle(answer).fontSize));
 answer.style.fontSize=`${upper}px`;
 if(answer.scrollHeight>answer.clientHeight||answer.scrollWidth>answer.clientWidth){
  let lower=17,best=17;
  while(lower<=upper){const size=Math.floor((lower+upper)/2);answer.style.fontSize=`${size}px`;
   if(answer.scrollHeight<=answer.clientHeight&&answer.scrollWidth<=answer.clientWidth){best=size;lower=size+1;}else upper=size-1;
  }
  answer.style.fontSize=`${best}px`;
 }
 answer.scrollTop=0;
}
function addWord(part,token){
 $('answer').classList.remove('thinking');answerParts.push({text:part,born:time});
 words=markdown($('answer'),answerParts,true);
 fitAnswer();
}
function ridge(){const c=$('reader'),ctx=c.getContext('2d'),W=780,H=200;ctx.clearRect(0,0,W,H);const peaks=new Map();rows.forEach(row=>Object.entries(row).forEach(([id,z])=>peaks.set(id,Math.max(peaks.get(id)||0,z))));const ids=[...peaks].sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0])).slice(0,4).map(p=>p[0]);const zmax=Math.max(8,Math.ceil(Math.max(0,...peaks.values())+.5));$('ridge-labels').replaceChildren();ids.forEach((id,i)=>{const baseline=46+i*36;ctx.beginPath();ctx.moveTo(0,baseline);rows.forEach((row,j)=>ctx.lineTo(j*510/59,baseline-Math.max(0,row[id]||0)/zmax*68));ctx.lineTo(Math.max(0,rows.length-1)*510/59,baseline);ctx.closePath();ctx.fillStyle='#02061D';ctx.fill();ctx.strokeStyle=mode.mode==='telepathy'&&mode.phase!=='reveal'?'#F1E9D6':colour(id);ctx.lineWidth=2;ctx.stroke();const div=document.createElement('div');div.className='ridge-label';const title=document.createElement('span');title.textContent=mode.mode==='telepathy'&&mode.phase!=='reveal'?`SIGNAL ${i+1}`:label(id);const val=document.createElement('small');const z=rows.at(-1)?.[id]||0;val.textContent=z>.05?`${z.toFixed(1)} SD`:'—';div.append(title,val);$('ridge-labels').append(div);});}
function shareValues(){if(!shareTween)return currentShares||{};const p=Math.max(0,Math.min(1,(time-shareTween.born)/.6));return Object.fromEntries(shareTween.ids.map(id=>[id,(shareTween.from[id]||0)*(1-p)+(shareTween.to[id]||0)*p]));}
function drawShares(){if(!shareTween)return;const values=shareValues();$('share-bar').querySelectorAll('span').forEach(span=>span.style.width=`${(values[span.dataset.faction]||0)*100}%`);if(time-shareTween.born>=.6){currentShares=shareTween.to;shareTween=null;}}
function shares(event){const from=shareValues(),to=event.shares,ids=[...new Set([...Object.keys(from),...Object.keys(to)])];if(currentShares&&ids.some(id=>Math.abs((from[id]||0)-(to[id]||0))>1e-9))shareTween={from,to,ids,born:time};else shareTween=null;currentShares=to;lastTick=event;$('share-bar').querySelectorAll('span').forEach(e=>e.remove());$('share-legend').replaceChildren();Object.entries(event.shares).sort((a,b)=>b[1]-a[1]).forEach(([id,value])=>{const segment=document.createElement('span');segment.dataset.faction=id;segment.style.width=`${(shareTween?(from[id]||0):value)*100}%`;segment.style.background=id==='Neutral'?'#526074':colour(id);$('share-bar').append(segment);const item=document.createElement('span');const name=document.createElement('b');name.textContent=label(id);item.append(name,document.createTextNode(` ${(value*100).toFixed(0)}%`));item.style.borderBottom=`2px solid ${id==='Neutral'?'#526074':colour(id)}`;$('share-legend').append(item);});if(shareTween)ids.filter(id=>!(id in to)).forEach(id=>{const segment=document.createElement('span');segment.dataset.faction=id;segment.style.width=`${(from[id]||0)*100}%`;segment.style.background=id==='Neutral'?'#526074':colour(id);$('share-bar').append(segment);});}
function blind(){return mode.mode==='telepathy'&&mode.phase!=='reveal';}
function playing(){
 if(!mode.mode||mode.phase==='idle')return false;
 if(mode.mode!=='war')return true;
 return answerPushed||!!mode.injection||Object.entries(lastTick?.shares||{}).some(([id,value])=>id!=='Neutral'&&value>0);
}
function refreshWaiting(){
 const waiting=!playing();document.body.classList.toggle('waiting',waiting);
 if(waiting)$('mode-caption').hidden=true;
 text('mode',waiting?'WAITING':roundLabels[mode.mode]||'READY');
 text('instruction',waiting?'How to play: !join':mode.mode==='telepathy'?(mode.phase==='reveal'?'Next round soon · !rank for your score':'How to play: !guess word · !rank'):'How to play: !join · !push word · !guess word');
 if(mode.phase!=='reveal'){
  const leader=Object.entries(lastTick?.shares||{}).filter(([id,value])=>id!=='Neutral'&&value>0).sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0]))[0]?.[0];
  headline(currentTarget?label(currentTarget):mode.injection?label(mode.injection):leader?label(leader):null);
 }
}
function headline(target){
 if(!playing()){text('round-headline','Waiting for chat. Type !join to play.');return;}
 if(mode.phase==='guessing'){$('round-headline').replaceChildren(document.createTextNode('Guess what the AI is thinking!'));return;}
 const word=blind()?'???':target||'an idea';
 $('round-headline').replaceChildren(document.createTextNode('Chat is trying to make the AI think about... '));
 const span=document.createElement('span');span.id='target-word';span.textContent=word;$('round-headline').append(span);
}
function simpleReadout(e){
 if(blind()){text('ai-guess','Hidden until the reveal');text('nerd-values','Hidden until the reveal');return;}
 text('ai-guess',e.readout?.top?label(e.readout.top):'No clear thought yet');
 if(e.applied)headline(label(e.applied));
 if(e.sky)text('nerd-values',`Push strength: ${Number(lastTick?.beta||0).toFixed(2)} · signal drive: ${Number(e.sky.drive||0).toFixed(3)}`);
}
function countdown(){if(deadline!=null){const left=Math.max(0,Math.ceil(deadline-time));text('countdown',left>0?`${left}s left`:mode.phase==='guessing'?'Time is up':'Thinking...');}}
function reveal(e){
 const version=++revealVersion;$('reveal').hidden=true;$('winner').hidden=true;
 if(e.phase!=='reveal')return;
 text('countdown','The answer is...');$('round-headline').replaceChildren(document.createTextNode('Ready for the answer?'));
 later(()=>{if(version!==revealVersion||mode.phase!=='reveal')return;
  text('reveal',e.reveal?label(e.reveal):'A new thought');$('reveal').hidden=false;
  text('winner',e.winner?`${e.winner} guessed it!`:'Nobody guessed it. Try the next round!');$('winner').hidden=false;
  $('round-headline').replaceChildren(document.createTextNode('The AI was thinking about...'));text('countdown','Revealed!');
  text('ai-guess',e.probe_top?label(e.probe_top):'No guess saved');
 },reduced?.1:1.4);
}
function renderMvp(card){
 const version=++mvpVersion;
 if(!card?.mvp||(mode.mode==='telepathy'&&mode.phase!=='reveal')){$('mvp').hidden=true;return;}
 $('mvp').textContent=`ROUND MVP · ${card.mvp.name} · ${Number(card.mvp.points).toFixed(2)} POINTS`;
 $('mvp').hidden=false;later(()=>{if(version===mvpVersion)$('mvp').hidden=true;},5);
 if(mode.phase==='reveal')text('scoreboard',(card.board?.stream||[]).slice(0,5).map(row=>`${row.name} ${Number(row.points).toFixed(2)}`).join(' · '));
}
function renderHistory(){ $('history').replaceChildren();history.slice(-3).forEach(h=>{const a=document.createElement('article'),b=document.createElement('b'),body=document.createElement('div');b.textContent=h.title;markdown(body,[{text:h.text,born:0}]);a.append(b,body);$('history').append(a);}); }
function modeEvent(e){
 const change=e.mode!==mode.mode||e.panel!==mode.panel;
 const newAnswer=e.answer!==mode.answer||e.panel!==mode.panel||e.mode!==mode.mode;
 if(newAnswer&&['armed','generating'].includes(e.phase)){
  if($('answer').textContent)history.push({title:answerPushed?(mode.mode?.toUpperCase()||'TEAM ROUND'):'AI ANSWER',text:answerParts.map(p=>p.text).join('')});
  history=history.slice(-3);renderHistory();answerParts=[];answerPushed=false;currentTarget=null;
  $('mvp').hidden=true;$('answer').replaceChildren();fitAnswer(true);$('answer').classList.remove('thinking');
  const key=`${e.mode}/${e.answer}/${e.panel}`;
  later(()=>{if(`${mode.mode}/${mode.answer}/${mode.panel}`===key&&mode.phase==='generating'&&!$('answer').childNodes.length)$('answer').classList.add('thinking');},.6);
  words=[];queue=[];if(e.mode==='telepathy')rows=[];
 }
 mode=e;text('prompt',e.prompt);
 text('colour-label',e.colour_source==='readout'?"AI's guess colours":'Team colours');
 text('panel-label',e.mode==='attack'?`DEFENCE ${e.immune?'ON':'OFF'}`:'');
 $('immune-chip').hidden=!e.immune;text('immune-chip','Defence on');$('tamper').hidden=true;
 document.body.classList.toggle('blind',e.mode==='telepathy'&&e.phase!=='reveal');
 document.body.classList.toggle('revealed',e.phase==='reveal');
 if(blind())renderMvp(null);
 deadline=['armed','generating','guessing'].includes(e.phase)?(e.remaining!=null?time+e.remaining:e.phase==='generating'?time+12:null):null;
 refreshWaiting();if(blind())simpleReadout({});reveal(e);countdown();
 text('scoreboard',(e.scoreboard||[]).map(([user,score])=>`${user}  ${score}`).join(' · '));
 if(change&&playing()){
  const g=++generation;captionBorn=time;text('mode-caption',roundLabels[e.mode]||'READY');$('mode-caption').hidden=false;
  later(()=>{if(g===generation)$('mode-caption').hidden=true;},reduced?.1:1.7);
 }
 ridge();
}
const handlers = {
    push(e){const p=document.createElement('div');p.textContent=`${e.user} → ${label(e.faction)}`;$('pushes').prepend(p);while($('pushes').children.length>5)$('pushes').lastChild.remove();},
    tick(e){shares(e);refreshWaiting();if(!blind())text('nerd-values',`Push strength: ${Number(e.beta).toFixed(2)}`);},
    token(e){answerPushed=answerPushed||!!e.applied;if(e.applied)currentTarget=e.applied;refreshWaiting();simpleReadout(e);queue.push(...(e.text.match(/\S+\s*|\s+/g)||[]).map(part=>({part,token:e})));if(e.sky?.z){rows.push(e.sky.z);rows=rows.slice(-60);ridge();}},
    mode(e){modeEvent(e);},
    tamper(e){$('tamper').hidden=!mode.immune||!e.concepts.length;text('tamper','Tamper alarm · caught!');},
    badge(event){text('source',event.label);$('source').hidden=/^SIMULATED ×0$/.test(event.label);$('sim-source').hidden=!event.simulated_users||event.label.startsWith('SIMULATED');text('sim-source',event.simulated_users!=null?`SIMULATED ×${event.simulated_users}`:'');text('quality',event.quality||'');$('quality').hidden=!event.quality;},
    snapshot(e){
        const s=e.state;lastTick=null;currentTarget=null;answerPushed=false;
        $('answer').replaceChildren();$('pushes').replaceChildren();
        words=[];queue=[];rows=[];answerParts=[];nextWord=time;fitAnswer(true);
        catalog=s.concepts||[];catalog.forEach((c,i)=>{names.set(c.id,c.label||c.name||c.id.replaceAll('_',' ').toUpperCase());colours.set(c.id,palette[i%palette.length]);});
        if(s.badge)handlers.badge(s.badge);modeEvent(s.mode);if(s.tamper)handlers.tamper(s.tamper);
        history=(s.history||[]).map(h=>({title:h.tokens.some(t=>t.applied)?h.mode.mode.toUpperCase():'AI ANSWER',text:h.tokens.map(t=>t.text).join('')}));renderHistory();
        if(s.tick)handlers.tick(s.tick);if(s.layout)handlers.layout(s.layout);
        (s.tokens||[]).forEach(handlers.token);(s.pushes||[]).forEach(handlers.push);
        twitchState=s.connections?.twitch||'connected';engineState=s.connections?.engine||'connected';renderConnection();
        renderMvp(s.mvp?{mvp:s.mvp,board:s.leaderboard}:null);
    },
    connection(e){if(e.service==='twitch')twitchState=e.state;if(e.service==='engine')engineState=e.state;renderConnection();},
    guess(){},
    control(){},
    immune(e){mode.immune=e.enabled;$('immune-chip').hidden=!e.enabled;if(!e.enabled)$('tamper').hidden=true;},
    round(e){if(e.phase==='catalog'){let data;try{data=JSON.parse(e.message);}catch(_){return;}catalog=data.concepts||[];catalog.forEach((c,i)=>{names.set(c.id,c.label||c.id);colours.set(c.id,palette[i%palette.length]);});return;}if(e.phase==='end'){deadline=null;text('countdown','Next round soon');}if(e.phase!=='mvp')return;let card;try{card=JSON.parse(e.message);}catch(_){return;}renderMvp(card);},
    layout(e){if(Object.keys(e.alias||{}).length){if(lastTick)shares({...lastTick,shares:Object.fromEntries(Object.entries(lastTick.shares).map(([id,value])=>[e.alias[id]||id,value]))});rows=rows.map(row=>Object.fromEntries(Object.entries(row).map(([id,z])=>[e.alias[id]||id,z])));ridge();}},
};
function dispatch(e){if(!handlers[e.kind])throw Error(`Unknown event ${e.kind}`);handlers[e.kind](e);atlas.event(e);}
function step(dt){
if(!Number.isFinite(dt)||dt<0)throw Error('Expected nonnegative seconds');
const end=time+dt;
for(let pass=0;pass<10000;pass++){
  const at=Math.min(...jobs.map(j=>j.at),queue.length?Math.max(time,nextWord):Infinity);
  if(at>end)break;time=Math.max(time,at);
  const due=jobs.filter(j=>j.at<=time);jobs=jobs.filter(j=>j.at>time);due.forEach(j=>j.fn());
  if(queue.length&&time>=nextWord){const count=Math.max(1,Math.ceil(queue.length/18));for(let j=0;j<count&&queue.length;j++){const w=queue.shift();addWord(w.part,w.token);}nextWord=time+.035;}
}
time=end;
words.forEach(w=>{w.style.opacity=reduced?'1':Math.min(1,(time-Number(w.dataset.born))/.12);});
$('mode-caption').style.opacity=reduced?'1':Math.max(0,Math.min(1,(time-captionBorn)/.2,(1.7-time+captionBorn)/.35));
drawShares();countdown();atlas.step(dt);
}
function connect(){socket=new WebSocket(`${location.protocol==='https:'?'wss:':'ws:'}//${location.host}/ws`);socket.onopen=()=>{overlayConnected=true;renderConnection();};socket.onmessage=e=>dispatch(JSON.parse(e.data));socket.onclose=()=>{overlayConnected=false;renderConnection();later(connect,2);};socket.onerror=()=>socket.close();}
window.NousOverlay={step,dispatch,later,ready:document.fonts.ready,stats:()=>({...atlas.stats(),time,queuedWords:queue.length}),reset(){deadline=null;revealVersion++;time=0;jobs=[];queue=[];words=[];rows=[];mode={};history=[];answerParts=[];answerPushed=false;currentTarget=null;lastTick=null;currentShares=null;shareTween=null;nextWord=0;$('answer').replaceChildren();$('history').replaceChildren();$('pushes').replaceChildren();fitAnswer(true);refreshWaiting();}};
document.fonts.ready.then(()=>fitAnswer(true));
refreshWaiting();
if(!manual){let previous;function frame(t){if(previous!=null){atlas.frame(t-previous);window.NousOverlay.step((t-previous)/1000);}previous=t;requestAnimationFrame(frame);}requestAnimationFrame(frame);}
if(!location.pathname.endsWith('fixture.html'))connect();
else {const trace=document.createElement('script');trace.src='trace_data.js';trace.onload=()=>{const fixture=document.createElement('script');fixture.src='fixture.js';document.head.append(fixture);};document.head.append(trace);}
})();

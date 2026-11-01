(() => {
'use strict';
const $=id=>document.getElementById(id);let ready=false, timer;
async function call(path,body){const response=await fetch(`/api/${path}`,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json'},...(body===undefined?{}:{body:JSON.stringify(body)})});if(!response.ok)throw Error(await response.text());return response.json();}
function tick(id){$(id).textContent='✓';$(id).classList.add('done');}
async function poll(){try{const s=await call('welcome');ready=true;$('status').textContent=s.message;
 if(s.has_app_code){tick('app-tick');$('app-help').hidden=true;}
 if(s.status==='waiting'){const url=new URL(s.url);if(url.protocol!=='https:')throw Error('Please open Twitch directly to finish signing in.');$('device').hidden=false;$('device-code').textContent=s.code;$('device-link').href=url.href;}
 if(['connected','preparing','connecting','live'].includes(s.status)){tick('login-tick');$('device').hidden=true;$('go-live').disabled=['preparing','connecting'].includes(s.status);if(s.name&&!$('channel').value)$('channel').value=s.name;}
 if(s.status==='error'){if(!s.signed_in){$('app-help').hidden=false;$('app-tick').textContent='1.';$('app-tick').classList.remove('done');$('login-tick').textContent='2.';$('login-tick').classList.remove('done');}$('login').textContent='Try login again';$('go-live').disabled=!s.signed_in;$('go-live').textContent='Retry connection';}
 if(s.status==='live'){tick('channel-tick');$('open-game').hidden=false;$('go-live').textContent='Connected ✓';$('connect-help').textContent='Your chat is ready. Open the game and try !join.';}
 }catch(error){$('status').textContent='Open NOUS with setup.bat or nous start to unlock this page. '+error.message;}
 timer=setTimeout(poll,1200);}
$('try-demo').onclick=async()=>{try{if(!ready)throw Error('Wait a moment while NOUS opens.');await call('demo',{});location.assign('/overlay/');}catch(error){$('status').textContent=error.message;}};
$('connect-path').onclick=()=>{$('twitch-steps').hidden=false;$('twitch-steps').scrollIntoView({behavior:'smooth'});};
$('login').onclick=async()=>{try{await call('login',{app_code:$('app-code').value});$('status').textContent='Opening Twitch sign-in...';}catch(error){$('login-help').textContent=error.message;}};
$('go-live').onclick=async()=>{try{await call('connect',{channel:$('channel').value});$('go-live').disabled=true;$('connect-help').textContent='Getting your game ready. You can try the recording while you wait.';}catch(error){$('connect-help').textContent=error.message;}};
async function boot(){const token=location.hash.slice(1);history.replaceState(null,'',location.pathname);if(token){try{const response=await fetch('/api/bootstrap',{method:'POST',headers:{Authorization:`Bearer ${token}`}});if(!response.ok)throw Error('Please open NOUS again from setup.bat.');}catch(error){$('status').textContent=error.message;return;}}await poll();window.NOUS_WELCOME_READY=true;}
addEventListener('pagehide',()=>clearTimeout(timer));boot();
})();

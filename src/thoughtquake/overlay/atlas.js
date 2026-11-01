/* Smooth fields from token measurements. Coordinates and aliases arrive from the server. */
(() => {
  "use strict";
  const palette = ["#5B8CFF", "#F2C340", "#2FC79A", "#F0604A", "#E877A6", "#7CD0EE", "#A685E6"];
  const clamp = (v, a=0, b=1) => Math.max(a, Math.min(b, v));
  const ease = v => 1 - Math.pow(1-clamp(v), 3);
  const rgb = hex => [1,3,5].map(i => parseInt(hex.slice(i,i+2),16)/255);
  const vertex = `#version 300 es
  precision highp float;
  out vec2 uv;
  void main(){vec2 p=vec2((gl_VertexID<<1)&2,gl_VertexID&2);uv=p;gl_Position=vec4(p*2.-1.,0.,1.);}`;
  const fragment = `#version 300 es
  precision highp float;
  in vec2 uv;out vec4 outColor;
  uniform vec4 uStar[30];uniform vec3 uColor[30];uniform float uPulse[30];uniform vec4 uRing[24];
  uniform int uCount,uRings;uniform float uTime,uBreath,uDrive,uLens,uSat,uSplit,uTransparent,uGain;
  uniform vec2 uHead;
  float line(float v){float k=floor(v+.5);float w=max(fwidth(v)*.62,.018)*(mod(abs(k),5.)<.5?1.9:1.);return 1.-smoothstep(0.,w,abs(v-k));}
  void main(){
    vec2 q=vec2(uv.x*1920.,(1.-uv.y)*1080.);float phi=0.,sw=0.,wave=0.;vec3 tint=vec3(0.);
    for(int i=0;i<30;i++){if(i>=uCount)break;vec4 s=uStar[i];vec2 delta=q-s.xy;float r=length(delta)/150.,r2=r*r;
      float g=inversesqrt(1.+r2)/(1.+r2);float glow=clamp(s.w/6.,0.,1.);
      float w=s.z*2.2+max(0.,s.w-1.)/6.*.55+glow*.25+uPulse[i]*.5+.09;
      phi+=w*g;tint+=uColor[i]*w*g;wave+=uPulse[i]*g*sin(11.*r-1.7*uTime);
      float signI=mod(float(i),2.)<.5?1.:-1.;
      float phase=2.9*log(r2+.04)-.5*signI*uTime+1.7*float(i);
      float denominator=max(dot(delta,delta),.00001);
      float sinAngle=2.*delta.x*delta.y/denominator;
      float cosAngle=(delta.x*delta.x-delta.y*delta.y)/denominator;
      float bandBase=.5+.5*(signI*sinAngle*cos(phase)+cosAngle*sin(phase));
      float band=bandBase*bandBase;
      sw+=w*g*band*(.6+.4*smoothstep(0.,.5,r2));
    }
    float v=log(1.6*phi+.02)*5.2+.5*uDrive*wave;
    float lens=uLens*exp(-dot(q-uHead,q-uHead)/150000.);float d=.035+.22*lens;
    vec3 contours=vec3(line(v+d),line(v),line(v-d));tint=mix(vec3(.80,.88,1.),tint/max(phi,.001),uSat);
    float vignette=clamp(1.-length((q-vec2(1200.,540.))/vec2(1450.,980.)),0.,1.);
    float neb=(.5+.5*sin(q.x*.0023+q.y*.0012+uTime*.023))*(.5+.5*sin(q.y*.0031-q.x*.0011-uTime*.018));
    vec3 ground=mix(vec3(.008,.022,.092),vec3(.022,.07,.25),vignette)+vec3(.006,.026,.085)*neb*(.45+.9*uBreath);
    ground*=1.+.22*uBreath*sin(1.15*uTime);if(uTransparent>.5)ground=vec3(0.);
    float sk=clamp(3.4*sw,0.,2.);vec3 ramp=mix(vec3(.04,.16,.62),vec3(.5,.8,1.),clamp(sk,0.,1.));
    ramp=mix(ramp,vec3(1.,.8,.28),clamp((sk-1.1)/.9,0.,1.));
    vec3 c=ground+contours*tint*.10+ramp*sk*(.14+.12*uBreath)*(uTransparent>.5?.45:1.);
    for(int i=0;i<24;i++){if(i>=uRings)break;vec4 ring=uRing[i];float rr=length(q-ring.xy)-1100.*ring.z;
      c+=vec3(.05,.13,.34)*exp(-rr*rr/1900.)*ring.w*max(0.,1.-ring.z/1.6);}
    float seam=exp(-pow((q.x-uSplit)/3.,2.));c+=vec3(.22,.32,.42)*seam;
    c*=uGain;c=c/(1.+c*.65);
    float a=uTransparent>.5?clamp(max(c.r,max(c.g,c.b))*1.15,0.,1.):1.;
    outColor=vec4(uTransparent>.5?c/max(a,.00001):c,a);
  }`;
  class Atlas {
    constructor(){
      this.canvas=document.getElementById("atlas-field");this.fx=document.getElementById("atlas-fx");this.ctx=this.fx.getContext("2d");
      this.fx.width=1920;this.fx.height=1080;this.t=0;this.stars=[];this.catalog=new Map();this.shares={};this.beta=0;
      this.drive=0;this.breath=0;this.conf=0;this.lens=0;this.rings=[];this.shocks=[];this.trail=[];this.offTrail=[];this.ghost=[];
      this.head={x:1250,y:578};this.mode="war";this.panel="main";this.phase="generating";this.modeStart=-10;this.revealStart=-10;
      this.blind=false;this.layoutStart=0;this.samples=[];this.frameTimes=[];this.lastLeader=null;
      const query=new URLSearchParams(location.search);this.manual=query.has("manual");this.transparent=query.get("bg")==="transparent";
      this.scale=clamp(Number(query.get("scale")||1),.5,1);this.motion=!matchMedia("(prefers-reduced-motion: reduce)").matches;
      this.gl=query.has("nogl")?null:this.canvas.getContext("webgl2",{alpha:true,premultipliedAlpha:false,antialias:false,preserveDrawingBuffer:true});
      if(this.gl){try{this.initGL();}catch(_){this.gl=null;this.canvas.replaceWith(this.canvas.cloneNode());this.canvas=document.getElementById("atlas-field");}}
      if(!this.gl){this.field=this.canvas.getContext("2d");this.buffer=document.createElement("canvas");this.buffer.width=160;this.buffer.height=90;this.bufferCtx=this.buffer.getContext("2d");}
      this.renderer=this.gl?"gl":"2d";document.getElementById("stage").dataset.renderer=this.renderer;this.resize();
    }
    initGL(){const gl=this.gl;const compile=(type,source)=>{const s=gl.createShader(type);gl.shaderSource(s,source);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(s));return s;};
      this.program=gl.createProgram();gl.attachShader(this.program,compile(gl.VERTEX_SHADER,vertex));gl.attachShader(this.program,compile(gl.FRAGMENT_SHADER,fragment));gl.linkProgram(this.program);
      if(!gl.getProgramParameter(this.program,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(this.program));gl.useProgram(this.program);
      this.uniform={};["uStar","uColor","uPulse","uRing","uCount","uRings","uTime","uBreath","uDrive","uLens","uSat","uSplit","uTransparent","uGain","uHead"].forEach(n=>this.uniform[n]=gl.getUniformLocation(this.program,n));
    }
    resize(){this.canvas.width=Math.round(1920*this.scale);this.canvas.height=Math.round(1080*this.scale);if(this.gl)this.gl.viewport(0,0,this.canvas.width,this.canvas.height);}
    frame(ms){this.frameTimes.push(ms);if(this.frameTimes.length>240)this.frameTimes.shift();this.samples.push(ms);if(this.samples.length===60){if(this.samples.reduce((a,b)=>a+b,0)/60>22&&this.scale>.5){this.scale=Math.max(.5,this.scale-.125);this.resize();}this.samples=[];}}
    color(id){return this.blind?"#FFF3C8":palette[(this.catalog.get(id)?.color_index||0)%7];}
    layout(event){
      const old=new Map(this.stars.map(s=>[s.id,s]));const revealed=Object.keys(event.alias||{}).length>0;
      this.stars=Object.entries(event.points).slice(0,30).map(([key,point])=>{const id=event.alias?.[key]||key,prior=old.get(key)||old.get(id);const x=1250+point[0]*350,y=578+point[1]*350;
        return {key,id,x:prior?.x??x,y:prior?.y??y,fromX:prior?.x??x,fromY:prior?.y??y,toX:x,toY:y,z:prior?.z||0,glow:prior?.glow||0,pressure:(this.shares[key]??this.shares[id]??0)*this.beta,pulse:0};});
      this.layoutStart=this.t;if(revealed)this.revealStart=this.t;
    }
    event(event){
      if(event.kind==="layout")this.layout(event);
      if(event.kind==="snapshot"){if(this.trail.length){this.trail=[];this.rings=[];this.shocks=[];}this.catalog=new Map(event.state.concepts.map(c=>[c.id,c]));if(event.state.layout)this.layout(event.state.layout);this.event(event.state.mode);this.event(event.state.tick);for(const token of event.state.tokens)this.event(token);}
      if(event.kind==="tick"){this.shares=event.shares;this.beta=event.beta;const leader=Object.keys(this.shares).filter(k=>k!=="Neutral").sort((a,b)=>this.shares[b]-this.shares[a]||a.localeCompare(b))[0];
        if(this.lastLeader&&leader!==this.lastLeader)this.shocks.push({x:this.head.x,y:this.head.y,born:this.t,amp:.45,type:"leader"});this.lastLeader=leader;
        for(const s of this.stars)s.pressure=(this.shares[s.id]||0)*this.beta;}
      if(event.kind==="mode"){
        if(event.mode!==this.mode||this.modeStart===-10){this.modeStart=this.t;if(event.mode==="attack")this.offTrail=[];}
        this.mode=event.mode;this.panel=event.panel||"main";this.phase=event.phase;this.blind=this.mode==="telepathy"&&this.phase!=="reveal";
        if(this.panel==="on")this.ghost=this.offTrail.map(p=>({...p}));if(this.phase==="reveal")this.revealStart=this.t;
      }
      if(event.kind==="immune"&&event.enabled)this.shocks.push({x:this.head.x,y:this.head.y,born:this.t,amp:.6,type:"immune"});
      if(event.kind==="token"&&event.sky){
        const sky=event.sky;this.drive=clamp(sky.drive||0);this.residual=(sky.residual||0)/Math.max(sky.median||1,1e-8);
        for(const s of this.stars){s.z=Number(sky.z?.[s.key]??sky.z?.[s.id]??0);s.glow=clamp(s.z/6);s.pulse=clamp(sky.pulse?.[s.key]??sky.pulse?.[s.id]??0);}
        this.findHead();this.trail.push({...this.head,width:clamp(this.residual,.6,5),born:this.t});this.trail=this.trail.slice(-90);
        if(this.mode==="attack"&&this.panel==="off")this.offTrail.push({...this.head});
        this.rings.push({x:this.head.x,y:this.head.y,born:this.t,amp:.35+.5*Math.max(0,this.residual-.6)});this.rings=this.rings.slice(-24);
        if(sky.clamp>0){this.lens=clamp(sky.clamp);this.shocks.push({x:this.head.x,y:this.head.y,born:this.t,amp:this.lens,type:"immune"});this.shocks=this.shocks.slice(-12);}
      }
    }
    findHead(){if(!this.stars.length)return;const zmax=Math.max(...this.stars.map(s=>s.z));const weights=this.stars.map(s=>Math.exp((s.z-zmax)/1.15));const sum=weights.reduce((a,b)=>a+b,0);
      this.conf=clamp((zmax-1.5)/3);const x=this.stars.reduce((a,s,i)=>a+s.x*weights[i],0)/sum,y=this.stars.reduce((a,s,i)=>a+s.y*weights[i],0)/sum;
      this.head={x:1250+(x-1250)*this.conf,y:578+(y-578)*this.conf};}
    step(dt){this.t+=dt;const glide=this.motion?ease((this.t-this.layoutStart)/1.5):1;
      for(const s of this.stars){s.x=s.fromX+(s.toX-s.fromX)*glide;s.y=s.fromY+(s.toY-s.fromY)*glide;s.pulse*=Math.exp(-dt/1.1);}
      this.findHead();const target=this.conf*.65+Math.min(.5,2*this.drive);this.breath+=(target-this.breath)*(this.motion?1-Math.exp(-dt/.55):1);
      this.drive*=Math.exp(-dt/.6);this.lens*=Math.exp(-dt/1.8);this.rings=this.rings.filter(r=>this.t-r.born<1.6);this.shocks=this.shocks.filter(r=>this.t-r.born<1.8);
      this.draw();}
    draw(){if(this.gl)this.drawGL();else this.draw2D();this.drawFX();}
    drawGL(){const gl=this.gl,U=this.uniform;gl.useProgram(this.program);const stars=new Float32Array(120),colors=new Float32Array(90),pulses=new Float32Array(30),rings=new Float32Array(96);
      this.stars.forEach((s,i)=>{stars.set([s.x,s.y,s.pressure,s.z],i*4);colors.set(rgb(this.color(s.id)),i*3);pulses[i]=s.pulse;});
      this.rings.forEach((r,i)=>rings.set([r.x,r.y,this.t-r.born,r.amp],i*4));
      gl.uniform4fv(U.uStar,stars);gl.uniform3fv(U.uColor,colors);gl.uniform1fv(U.uPulse,pulses);gl.uniform4fv(U.uRing,rings);gl.uniform1i(U.uCount,this.stars.length);gl.uniform1i(U.uRings,this.motion?this.rings.length:0);
      const age=this.t-this.modeStart;const values={uTime:this.motion?this.t:0,uBreath:this.breath,uDrive:this.drive,uLens:this.lens,uSat:this.blind?0:.76,uSplit:this.mode==="attack"?1980-1300*ease(age/1.3):1980,uTransparent:this.transparent?1:0,uGain:this.blind?.55+.45*ease(age/1.7):1};
      for(const [key,value] of Object.entries(values))gl.uniform1f(U[key],value);gl.uniform2f(U.uHead,this.head.x,this.head.y);gl.drawArrays(gl.TRIANGLES,0,3);}
    draw2D(){const ctx=this.field,w=160,h=90,image=this.bufferCtx.createImageData(w,h);const time=this.motion?this.t:0;
      for(let y=0;y<h;y++)for(let x=0;x<w;x++){const qx=x*12,qy=y*12;let phi=0,sw=0;const tint=[0,0,0];
        this.stars.forEach((s,i)=>{const dx=qx-s.x,dy=qy-s.y,r=Math.hypot(dx,dy)/150,g=Math.pow(1+r*r,-1.5),weight=s.pressure*2.2+Math.max(0,s.z-1)/6*.55+s.glow*.25+s.pulse*.5+.09;
          phi+=weight*g;const col=rgb(this.color(s.id));for(let k=0;k<3;k++)tint[k]+=col[k]*weight*g;
          const sign=i%2?-1:1,band=Math.pow(.5+.5*Math.sin(2*sign*Math.atan2(dy,dx)+2.9*Math.log(r*r+.04)-.5*sign*time+1.7*i),2);sw+=weight*g*band;});
        const v=Math.log(1.6*phi+.02)*5.2,line=Math.exp(-Math.pow((v-Math.round(v))/.08,2)),sk=clamp(3.4*sw,0,2),neb=(.5+.5*Math.sin(qx*.0023+qy*.0012+time*.023))*(.5+.5*Math.sin(qy*.0031-qx*.0011-time*.018));
        const c=[.008,.022,.092].map((base,k)=>{const ramp=sk<1?[.04,.16,.62][k]*(1-sk)+[.5,.8,1][k]*sk: [.5,.8,1][k]*(2-sk)+[1,.8,.28][k]*(sk-1);
          let value=(this.transparent?0:base+[.006,.026,.085][k]*neb)+line*(tint[k]/Math.max(phi,.001))*.10+ramp*sk*(.14+.12*this.breath)*(this.transparent?.45:1);return value/(1+value*.65);});
        const a=this.transparent?clamp(Math.max(...c)*1.15):1,offset=(y*w+x)*4;for(let k=0;k<3;k++)image.data[offset+k]=clamp(c[k]/Math.max(a,1e-6))*255;image.data[offset+3]=a*255;
      }
      this.bufferCtx.putImageData(image,0,0);ctx.clearRect(0,0,this.canvas.width,this.canvas.height);ctx.imageSmoothingEnabled=true;ctx.drawImage(this.buffer,0,0,this.canvas.width,this.canvas.height);}
    halo(x,y,r,color,alpha){const ctx=this.ctx;const gradient=ctx.createRadialGradient(x,y,Math.max(0,r*.65),x,y,r*1.28);gradient.addColorStop(0,"transparent");gradient.addColorStop(.45,color);gradient.addColorStop(.64,color);gradient.addColorStop(1,"transparent");ctx.globalAlpha=clamp(alpha);ctx.fillStyle=gradient;ctx.beginPath();ctx.arc(x,y,r*1.28,0,Math.PI*2);ctx.fill();}
    drawFX(){const ctx=this.ctx;ctx.clearRect(0,0,1920,1080);ctx.save();ctx.globalCompositeOperation="lighter";const t=this.motion?this.t:0;
      const wake=this.motion?ease((this.t-this.modeStart)/1.7):1;const pressureOrder=[...this.stars].sort((a,b)=>b.pressure-a.pressure||a.key.localeCompare(b.key));
      for(const s of this.stars){const e=Math.max(s.glow,2*s.pressure,s.pulse),rank=pressureOrder.indexOf(s);const visibility=this.mode==="war"?clamp(wake*1.6-rank/45):1;
        for(let r=0;r<3;r++){const radius=15+r*(13+12*e)+(3+7*e)*Math.sin(t*(1.1+.25*r)-1.1*r+9*s.x/1920);this.halo(s.x,s.y,Math.max(5,radius),this.blind?"#FFF3C8":r===0?"#FFD54A":this.color(s.id),(.16+.5*e)*(1-.26*r)*visibility);}
        ctx.globalAlpha=clamp(.5+e*.5)*visibility;ctx.fillStyle=this.blind||e>.65?"#FFF3C8":"#FFD23F";ctx.shadowColor="#FFD54A";ctx.shadowBlur=18+18*e;ctx.beginPath();ctx.arc(s.x,s.y,Math.min(10,2.4+4*e),0,Math.PI*2);ctx.fill();ctx.shadowBlur=0;
      }
      const dominant=[...this.stars].sort((a,b)=>(2.4*b.pressure+Math.max(0,b.z-1.5)/6)-(2.4*a.pressure+Math.max(0,a.z-1.5)/6))[0];
      if(dominant){const k=2.4*dominant.pressure+Math.max(0,dominant.z-1.5)/6;if(k>.12)this.flames(dominant,Math.min(k,1.5),t);}
      if(this.motion&&this.trail.length>1){ctx.globalAlpha=.42*this.conf;ctx.strokeStyle=this.blind?"#F1E9D6":"#E1C679";ctx.lineWidth=clamp(this.residual||1,.7,6);ctx.beginPath();this.trail.forEach((p,i)=>i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y));ctx.stroke();}
      if(this.mode==="attack"&&this.panel==="on"&&this.ghost.length){ctx.globalAlpha=.78;ctx.strokeStyle="#F0604A";ctx.lineWidth=3;ctx.setLineDash([9,9]);ctx.beginPath();this.ghost.forEach((p,i)=>i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y));ctx.stroke();ctx.setLineDash([]);const p=this.ghost.at(-1);ctx.fillStyle="#F0604A";ctx.beginPath();ctx.arc(p.x,p.y,5,0,Math.PI*2);ctx.fill();}
      if(this.motion)for(const shock of this.shocks){const age=clamp((this.t-shock.born)/1.8),radius=20+360*ease(age);for(let c=0;c<3;c++){ctx.globalAlpha=(1-age)*shock.amp*.65;ctx.strokeStyle=["#5B8CFF","#F2C340","#F0604A"][c];ctx.lineWidth=2;ctx.beginPath();ctx.arc(shock.x+(c-1)*5,shock.y,radius+c*4,0,Math.PI*2);ctx.stroke();}
        if(shock.type==="immune"){ctx.fillStyle="#E1C679";ctx.globalAlpha=(1-age)*shock.amp;for(let i=0;i<12;i++)ctx.fillRect(1040+i*55,0,3,10+(i%3)*8);}}
      const revealAge=(this.t-this.revealStart)/1.5;if(this.motion&&revealAge>=0&&revealAge<=1){ctx.strokeStyle="#E1C679";ctx.globalAlpha=(1-revealAge)*.35;ctx.lineWidth=70;ctx.beginPath();ctx.arc(1250,578,1900*ease(revealAge),0,Math.PI*2);ctx.stroke();}
      const warAge=(this.t-this.modeStart)/1.7;if(this.motion&&this.mode==="war"&&warAge>=0&&warAge<=1){ctx.strokeStyle="#F1E9D6";ctx.globalAlpha=(1-warAge)*.6;ctx.lineWidth=1.5;ctx.beginPath();ctx.arc(1250,578,350*ease(warAge),0,Math.PI*2);ctx.stroke();ctx.fillStyle="#02061D";ctx.globalAlpha=1-warAge;ctx.fillRect(0,0,1920,80*(1-warAge));ctx.fillRect(0,1080-80*(1-warAge),1920,80*(1-warAge));}
      ctx.restore();this.labels();}
    flames(s,k,t){const ctx=this.ctx;ctx.save();ctx.shadowColor="#FFC446";ctx.shadowBlur=30;const heights=[.5,.72,.92,1,.88,.66,.46];
      for(let i=0;i<7;i++){const phase=i*1.7,h=(70+340*k)*heights[i]*(1+.06*Math.sin(1.7*t+phase)),x=s.x+(i-3)/3*1.1*(14+22*k),width=6+9*k,sway=16*(.4+k)*Math.sin(.9*t+phase),y=s.y;
        const gradient=ctx.createLinearGradient(0,y,0,y-h);gradient.addColorStop(0,"transparent");gradient.addColorStop(.12,"#FFC44680");gradient.addColorStop(.45,"#E1C67942");gradient.addColorStop(.78,"#5B8CFF24");gradient.addColorStop(1,"transparent");ctx.fillStyle=gradient;ctx.globalAlpha=1;ctx.beginPath();ctx.moveTo(x-width,y);ctx.bezierCurveTo(x-width*1.8,y-h*.3,x+sway-width,y-h*.7,x+sway,y-h);ctx.bezierCurveTo(x+sway+width,y-h*.65,x+width*1.5,y-h*.3,x+width,y);ctx.fill();}
      if(k>.45||s.pressure>.25)this.halo(s.x,s.y,30+25*k,"#FFD54A",.38);ctx.restore();}
    labels(){if(this.blind)return;const ctx=this.ctx;ctx.save();ctx.font='20px Plex';ctx.textBaseline="middle";const boxes=[];
      const top=[...this.stars].filter(s=>this.catalog.has(s.id)).sort((a,b)=>(b.z+9*b.pressure)-(a.z+9*a.pressure)||a.key.localeCompare(b.key)).slice(0,4);
      for(const s of top){const label=(this.catalog.get(s.id)?.label||s.id).toUpperCase(),width=ctx.measureText(label).width+18;let x=clamp(s.x+20,910,1900-width),y=clamp(s.y+24,300,980);
        for(let attempt=0;attempt<16&&boxes.some(b=>Math.abs(y-b.y)<30&&x<b.x+b.w&&x+width>b.x);attempt++)y+=32;
        boxes.push({x,y,w:width});ctx.fillStyle="rgba(2,6,29,.86)";ctx.fillRect(x-7,y-15,width,30);ctx.fillStyle="#F1E9D6";ctx.fillText(label,x,y);}
      ctx.restore();}
    stats(){return {renderer:this.renderer,scale:this.scale,meanFrameMs:this.frameTimes.length?this.frameTimes.reduce((a,b)=>a+b,0)/this.frameTimes.length:0,frames:this.frameTimes.length,stars:this.stars.length};}
  }
  window.ThoughtquakeAtlas=new Atlas();
})();

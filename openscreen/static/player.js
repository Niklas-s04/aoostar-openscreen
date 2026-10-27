'use strict';
const output=document.querySelector('#output'),status=document.querySelector('#player-status');
let interval=1,failures=0,objectURL=null,configAt=0;
let playerId,reportedAt=0,lastReported='',reportTimer,reporting=false,reportPending=false,physicalSize=null;
const viewport=document.body;
try{playerId=sessionStorage.getItem('openscreen-player');}catch(error){}
if(!/^[a-f0-9]{32}$/.test(playerId||'')){
 playerId=Array.from(crypto.getRandomValues(new Uint8Array(16)),n=>n.toString(16).padStart(2,'0')).join('');
 try{sessionStorage.setItem('openscreen-player',playerId);}catch(error){}
}
const identity=document.createElement('span');identity.textContent='Player '+playerId.slice(0,8);
document.querySelector('.player-controls').prepend(identity);
async function reportSize(){
 if(document.hidden)return;
 if(reporting){reportPending=true;return;}
 const rect=viewport.getBoundingClientRect(),dpr=window.devicePixelRatio||1;
 const measured=physicalSize?.dpr===dpr?physicalSize:null;
 const width=Math.round(measured?.width??rect.width*dpr),height=Math.round(measured?.height??rect.height*dpr);
 if(!Number.isFinite(width)||!Number.isFinite(height)||width<64||height<64||width>3840||height>3840||width*height>8294400)return;
 const size=width+'x'+height;
 if(size===lastReported&&Date.now()-reportedAt<30000)return;
 reporting=true;
 try{const response=await fetch('/api/displays/report',{method:'POST',headers:{'Content-Type':'application/json','X-OpenScreen':'1'},body:JSON.stringify({id:playerId,width,height}),signal:AbortSignal.timeout(5000)});if(response.ok){lastReported=size;reportedAt=Date.now();}}catch(error){}
 finally{reporting=false;if(reportPending){reportPending=false;scheduleReport();}}
}
function scheduleReport(){clearTimeout(reportTimer);reportTimer=setTimeout(reportSize,200);}
if(window.ResizeObserver){
 const observer=new ResizeObserver(entries=>{
  const box=entries[0]?.devicePixelContentBoxSize;
  const size=box?.[0]||box;
  physicalSize=size&&Number.isFinite(size.inlineSize)&&Number.isFinite(size.blockSize)?{width:size.inlineSize,height:size.blockSize,dpr:window.devicePixelRatio||1}:null;
  scheduleReport();
 });
 try{observer.observe(viewport,{box:'device-pixel-content-box'});}catch(error){observer.observe(viewport);}
}
function viewportChanged(){physicalSize=null;scheduleReport();}
let dprQuery;
function watchDpr(){
 if(dprQuery)dprQuery.removeEventListener('change',dprChanged);
 dprQuery=matchMedia('(resolution: '+(window.devicePixelRatio||1)+'dppx)');
 dprQuery.addEventListener('change',dprChanged);
}
function dprChanged(){viewportChanged();watchDpr();}
watchDpr();
window.addEventListener('resize',viewportChanged);
window.addEventListener('orientationchange',viewportChanged);
window.visualViewport?.addEventListener('resize',viewportChanged);
document.addEventListener('fullscreenchange',viewportChanged);
document.addEventListener('visibilitychange',viewportChanged);
setInterval(reportSize,30000);
scheduleReport();
async function refresh(){
 let delay=interval*1000;
 try{
  if(document.hidden){setTimeout(refresh,1000);return;}
  if(Date.now()-configAt>30000){const response=await fetch('/api/config',{cache:'no-store',signal:AbortSignal.timeout(10000)});if(!response.ok)throw Error('Konfiguration nicht erreichbar');const config=await response.json();interval=Math.max(.5,Math.min(60,config.output?.interval||1));delay=interval*1000;configAt=Date.now();}
  const response=await fetch('/api/output.png?t='+Date.now(),{cache:'no-store',signal:AbortSignal.timeout(20000)});
  if(!response.ok)throw Error('Display nicht erreichbar');
  const blob=await response.blob();if(!blob.type.startsWith('image/'))throw Error('Ungültige Bildantwort');
  const url=URL.createObjectURL(blob);const frame=new Image();frame.src=url;
  try{await frame.decode();}catch(error){URL.revokeObjectURL(url);throw error;}
  output.src=url;if(objectURL)URL.revokeObjectURL(objectURL);objectURL=url;
  status.textContent='';document.body.classList.remove('failed');failures=0;
 }catch(error){failures++;delay=Math.min(30000,1000*2**Math.min(failures,5));status.textContent='Verbindung unterbrochen · erneuter Versuch in '+Math.round(delay/1000)+' s';document.body.classList.add('failed');}
 setTimeout(refresh,delay);
}
document.querySelector('#fullscreen').addEventListener('click',async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await document.documentElement.requestFullscreen();}catch(error){status.textContent='Vollbild ist in diesem Browser nicht verfügbar';}});
document.addEventListener('fullscreenchange',()=>{document.querySelector('#fullscreen').textContent=document.fullscreenElement?'Vollbild verlassen':'Vollbild';});
let hideTimer;function showControls(){document.body.classList.remove('quiet');clearTimeout(hideTimer);hideTimer=setTimeout(()=>document.body.classList.add('quiet'),3000);}
document.addEventListener('pointermove',showControls);document.addEventListener('pointerdown',showControls);document.addEventListener('keydown',showControls);showControls();refresh();

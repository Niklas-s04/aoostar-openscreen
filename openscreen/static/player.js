'use strict';
const output=document.querySelector('#output'),status=document.querySelector('#player-status');
let interval=1,failures=0,objectURL=null,configAt=0;
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

'use strict';
const displayDiscovery={serial:[],players:[],loaded:false,loading:false,broker:{devices:[],candidates:[]}};
async function refreshDisplays(){
 if(state.route!=='settings'||document.hidden)return;
 if(displayDiscovery.loading)return;
 displayDiscovery.loading=true;
 try{
  const data=await api('/api/displays');Object.assign(displayDiscovery,data,{loaded:true});
  const list=document.querySelector('#display-devices');
  if(list)list.innerHTML='<option value="auto">Automatisch</option>'+discoveredDevices().map(d=>`<option value="${esc(d.device)}">${esc(d.name)} · ${d.width} × ${d.height}${d.accessible?'':' · keine Berechtigung'}</option>`).join('');
  const players=document.querySelector('[name="output.player_id"]');
  if(players){const selected=players.value;players.innerHTML=playerOptions(selected);players.value=selected;}
  const candidates=document.querySelector('#broker-candidates');if(candidates)candidates.textContent=(data.broker?.candidates||[]).map(c=>`${c.name}: ${c.state} ${c.reason}`).join(' · ');
  const note=document.querySelector('#discovery-note');
  if(note)note.textContent=`${data.serial.length} serielle Kandidaten, ${data.players.length} Browser-Player, ${data.broker?.devices.length||0} bestätigte Broker-Displays. ${data.broker?.error||''}`;
 }catch(error){notice(error.message,true);}finally{displayDiscovery.loading=false;clearTimeout(displayDiscovery.timer);if(state.route==='settings')displayDiscovery.timer=setTimeout(refreshDisplays,5000);}
}
function playerOptions(selected){
 let html=option('','Keine automatische Browsergröße',selected);
 for(const p of displayDiscovery.players)html+=option(p.id,`Player ${p.id.slice(0,8)} · ${p.width} × ${p.height} (gemeldet)`,selected);
 if(selected&&!displayDiscovery.players.some(p=>p.id===selected))html+=option(selected,`Player ${selected.slice(0,8)} · offline`,selected);
 return html;
}
function deviceSettings(){
 if(!displayDiscovery.loading)setTimeout(refreshDisplays,0);
 return field('Serielles Gerät','device',state.config.device,'text','required list="display-devices" placeholder="auto oder Gerätepfad"')+
 `<datalist id="display-devices"><option value="auto">Automatisch</option>${discoveredDevices().map(d=>`<option value="${esc(d.device)}">${esc(d.name)} · ${d.width} × ${d.height}</option>`).join('')}</datalist>
 <div class="toolbar"><button type="button" id="refresh-displays">Displays suchen</button><button type="button" id="probe-display">Ausgabe prüfen / Größe erkennen</button></div>
 <p id="discovery-note" class="hint">Vorschlag auswählen oder Gerätepfad manuell eingeben. Unbekannte Geräte benötigen einen passenden Adapter.</p><p id="broker-candidates" class="hint"></p><p id="probe-result" class="hint" role="status"></p>`;
}
function discoverySettings(o){
 return select('Browser-Player als Größenreferenz','output.player_id',playerOptions(o.player_id||''))+check('Gemeldete Größe beim Speichern übernehmen','output.auto_size',o.auto_size!==false)+
 '<p class="hint">Player zuerst auf dem Zielgerät unter /display öffnen. Seine Kennung erscheint dort im Vollbild-Menü. Browsergrößen sind Näherungen; manuelle Breite/Höhe bleiben ohne automatische Übernahme möglich.</p>';
}
function outputDraft(form){
 const data=new FormData(form),config=structuredClone(state.config),kind=data.get('output.kind');
 config.device=String(data.get('device')).trim();config.hardware_enabled=data.has('hardware_enabled');
 config.output={kind,width:kind!=='browser'?960:Number(data.get('output.width')),height:kind!=='browser'?376:Number(data.get('output.height')),rotation:Number(data.get('output.rotation')),fit:data.get('output.fit'),interval:Number(data.get('output.interval')),auto_size:data.has('output.auto_size'),player_id:data.get('output.player_id')||''};
 return config;
}
async function probeDisplay(config){
 const result=await api('/api/displays/probe','POST',config);
 const node=document.querySelector('#probe-result');if(node)node.textContent=result.message;
 for(const key of ['width','height']){const input=document.querySelector(`[name="output.${key}"]`);if(input)input.value=result.output[key];}
 config.output=result.output;
 return result;
}
document.addEventListener('click',async event=>{
 if(event.target.id==='refresh-displays')await refreshDisplays();
 if(event.target.id==='probe-display'){
  const button=event.target;button.disabled=true;
  try{await probeDisplay(outputDraft(document.querySelector('#settings-form')));state.formDirty=true;}
  catch(error){notice(error.message,true);}finally{button.disabled=false;}
 }
});
function discoveredDevices(){return document.querySelector('[name="output.kind"]')?.value==='broker'||(!document.querySelector('[name="output.kind"]')&&state.config.output.kind==='broker')?(displayDiscovery.broker?.devices||[]):displayDiscovery.serial;}

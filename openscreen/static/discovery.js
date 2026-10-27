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
  refreshModes();
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
 <label class="field" id="device-mode-field" hidden><span>Gerätemodus</span><select name="output.mode_id" id="device-modes"><option value="">Automatisch / anhand der Größe</option></select></label>
 <div class="toolbar"><button type="button" id="refresh-displays">Displays suchen</button><button type="button" id="probe-display">Ausgabe prüfen / Größe erkennen</button><button type="button" id="test-display">Testbild anzeigen</button></div>
 <div id="display-trial" class="callout" hidden role="status"></div>
 <p id="discovery-note" class="hint">Vorschlag auswählen oder Gerätepfad manuell eingeben. Unbekannte Geräte benötigen einen passenden Adapter.</p><p id="broker-candidates" class="hint"></p><p id="probe-result" class="hint" role="status"></p>`;
}
function discoverySettings(o){
 return select('Browser-Player als Größenreferenz','output.player_id',playerOptions(o.player_id||''))+check('Gemeldete Größe beim Speichern übernehmen','output.auto_size',o.auto_size!==false)+
 '<p class="hint">Player zuerst auf dem Zielgerät unter /display öffnen. Seine Kennung erscheint dort im Vollbild-Menü. Gemeldet wird die verfügbare Renderfläche, nicht die native Panelauflösung. Ohne automatische Übernahme bleiben Breite/Höhe manuell einstellbar.</p>';
}
function outputDraft(form){
 const data=new FormData(form),config=structuredClone(state.config),kind=data.get('output.kind');
 config.device=String(data.get('device')).trim();config.hardware_enabled=data.has('hardware_enabled');
 const stored=config.output||{},detected=form.dataset.detectedOutput?JSON.parse(form.dataset.detectedOutput):{};
 config.output={...stored,...detected,kind,width:Number(form.querySelector('[name="output.width"]').value),height:Number(form.querySelector('[name="output.height"]').value),rotation:Number(data.get('output.rotation')),fit:data.get('output.fit'),interval:Number(data.get('output.interval')),auto_size:data.has('output.auto_size'),player_id:data.get('output.player_id')||''};
 if(stored.kind!==kind&&!form.dataset.detectedOutput){config.output.adapter_id=kind==='browser'?'browser':'aoostar';config.output.mode_id='';config.output.pixel_format='';}
 if(kind==='browser'){config.output.mode_id='';config.output.pixel_format='png-rgb';}
 if(kind==='broker')config.output.mode_id=String(data.get('output.mode_id')||'');
 return config;
}
async function probeDisplay(config){
 const result=await api('/api/displays/probe','POST',config);
 const origins={'adapter-profile':'Geräteprofil','device-report':'Geräteantwort','kernel-mode':'Betriebssystem','player-viewport':'Player-Renderfläche','browser-estimate':'Player-Renderfläche','manual':'Manuell'};
 const node=document.querySelector('#probe-result');if(node)node.textContent=`${result.message} Größenquelle: ${origins[result.size_source]||result.size_source||'Unbekannt'}. ${result.capabilities?.adapter_id?'Adapter: '+result.capabilities.adapter_id+'. ':''}Ein Testbild prüft zusätzlich Beschnitt, Farben und Lesbarkeit.`;
 for(const key of ['width','height']){const input=document.querySelector(`[name="output.${key}"]`);if(input)input.value=result.output[key];}
 config.output=result.output;
 const form=document.querySelector('#settings-form');if(form)form.dataset.detectedOutput=JSON.stringify(result.output);
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

function selectedBroker(){
 const device=document.querySelector('[name="device"]')?.value;
 const devices=displayDiscovery.broker?.devices||[];
 return device==='auto'?(devices.length===1?devices[0]:null):devices.find(d=>d.device===device);
}
function refreshModes(){
 const field=document.querySelector('#device-mode-field'),select=document.querySelector('#device-modes');if(!field||!select)return;
 const broker=document.querySelector('[name="output.kind"]')?.value==='broker';field.hidden=!broker;
 const modes=selectedBroker()?.capabilities?.modes||[],selected=select.value||state.config.output.mode_id||'';
 select.innerHTML=option('','Automatisch / anhand der Größe',selected)+modes.map(m=>option(m.id,`${m.width} × ${m.height} · ${m.pixel_format}`,selected)).join('');
}
document.addEventListener('change',event=>{
 if(['output.kind','device'].includes(event.target.name))refreshModes();
 if(event.target.id==='device-modes'){
  const selected=selectedBroker(),mode=selected?.capabilities?.modes.find(m=>m.id===event.target.value);
  if(mode){const form=document.querySelector('#settings-form');form.dataset.detectedOutput=JSON.stringify({adapter_id:selected.capabilities.adapter_id,mode_id:mode.id,pixel_format:mode.pixel_format});for(const key of ['width','height'])form.querySelector(`[name="output.${key}"]`).value=mode[key];}
 }
});

async function updateDisplayTrial(){
 const box=document.querySelector('#display-trial');if(!box)return;
 const trial=state.status.trial;
 box.hidden=!trial;
 const save=document.querySelector('#settings-form [type="submit"]');if(save)save.disabled=Boolean(trial);
 if(trial)box.innerHTML=`<p>Testbild aktiv · noch ${trial.remaining} Sekunden. Prüfen Sie alle vier Ecken, Farben, Kreisform und Schrift auf dem Zielgerät. Ohne Bestätigung bleiben die bisherigen Einstellungen erhalten.</p><button type="button" id="confirm-display-trial" ${trial.sent?'':'disabled'}>Bild korrekt · Einstellungen übernehmen</button> <button type="button" id="cancel-display-trial">Abbrechen</button>`;
}
document.addEventListener('click',async event=>{
 const action=event.target.id;if(!['test-display','confirm-display-trial','cancel-display-trial'].includes(action))return;
 event.target.disabled=true;
 try{
  if(action==='test-display'){
   const form=document.querySelector('#settings-form'),config=outputDraft(form),data=new FormData(form);
   config.title=String(data.get('title')).trim();config.rotation=Number(data.get('rotation'));
   await api('/api/displays/trial','POST',config);
  }else{
   const trial=state.status.trial;if(!trial)throw Error('Displaytest ist nicht mehr aktiv');
   await api(`/api/displays/trial/${trial.id}/${action==='confirm-display-trial'?'confirm':'cancel'}`,'POST',{});
   state.config=await api('/api/config');state.formDirty=false;
  }
  state.status=await api('/api/status');await updateDisplayTrial();
  if(action!=='test-display')render();
 }catch(error){notice(error.message,true);}finally{event.target.disabled=false;}
});
document.addEventListener('change',event=>{if(['output.kind','device'].includes(event.target.name)){const form=document.querySelector('#settings-form');if(form)delete form.dataset.detectedOutput;}});
setInterval(()=>{if(typeof state!=='undefined'&&state.route==='settings'&&state.status)updateDisplayTrial();},1000);

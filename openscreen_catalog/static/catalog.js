'use strict';
const $=(s,root=document)=>root.querySelector(s);
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const state={config:null,route:'display',page:'welcome'};
const option=(value,label,current)=>`<option value="${esc(value)}" ${value===current?'selected':''}>${esc(label)}</option>`;
const field=(label,name,value,type='text',attrs='')=>`<label class="field"><span>${esc(label)}</span><input name="${name}" type="${type}" value="${esc(value)}" ${attrs}></label>`;
const select=(label,name,options)=>`<label class="field"><span>${esc(label)}</span><select name="${name}" aria-label="${esc(label)}">${options}</select></label>`;
const check=(label,name,checked,value='on')=>`<label class="check"><input name="${name}" type="checkbox" value="${esc(value)}" ${checked?'checked':''}><span>${esc(label)}</span></label>`;
const heading=(title,description,action='')=>`<div class="page-heading"><div><h1>${title}</h1><p>${description}</p></div>${action}</div>`;
const sourceOptions=()=>'';
function notice(message,error=false){const node=$('#notice');node.textContent=message;node.hidden=false;node.className=error?'error':'';}
async function api(path,method='GET',data){const response=await fetch(path,{method,headers:method==='GET'?{}:{'Content-Type':'application/json','X-OpenScreen':'1'},body:data===undefined?undefined:JSON.stringify(data)});const result=await response.json();if(!response.ok)throw Error(typeof result.detail==='string'?result.detail:'Ungültige Eingabe');return result;}
function render(){ $('#main').innerHTML=editorDisplay(); }
window.addEventListener('DOMContentLoaded',async()=>{try{
 state.config=await api('/api/config');state.page=state.config.selected_page;
 // This UI offers only elements backed by actual catalog capabilities.
 for(const key of ['metric','bar','ring','chart'])delete elementKinds[key];
 render();
}catch(error){notice(error.message,true);}});

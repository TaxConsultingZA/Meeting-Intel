// Synthetic-only browser verification of the actual Admin client and stylesheet.
import path from 'node:path';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';
import { createServer } from '../frontend/node_modules/vite/dist/node/index.js';
import { chromium } from '../frontend/node_modules/playwright/index.mjs';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../frontend');
const output = path.resolve(root, '../artifacts/processing-audit-five');
fs.mkdirSync(output, {recursive:true});
const id = '00000000-0000-0000-0000-000000000001';
const time = '2026-11-02T08:00:00Z';
const job = {job_id:id,status:'failed',attempts:3,created_at:time,confirmed_submissions:1,submission_evidence:'accepted_event',submission_uncertain:false,provider_status:'completed',audio_duration_seconds:18,processing_duration_seconds:12,token_usage:[{event_id:'synthetic-usage',occurred_at:time,prompt_tokens:3,completion_tokens:2,total_tokens:5}],failure:{stage:'extraction',category:'timeout'},actual_cost:null,estimated_cost:null,cost_status:'unknown'};
const audit = {id,occurred_at:time,event_type:'provider.submitted',outcome:'succeeded',actor_type:'system',actor_id:'recording_worker',actor_upn:null,resource_type:'recording_job',resource_id:id,job_id:id,meeting_id:null,correlation_id:id,metadata:{}};
const api = `export class ApiError extends Error {};
export async function getAuditEvents(token, filters, cursor) { window.auditQueries ??= []; window.auditQueries.push(filters); if(cursor) return {"items": [], "has_more": false, "next_cursor": null, "window_start": "2026-11-02T08:00:00Z", "window_end": "2026-11-02T08:00:00Z"}; return ${JSON.stringify({items:Array.from({length:29},(_,i)=>({...audit,id:`00000000-0000-4000-8000-${String(i+1).padStart(12,"0")}`})),has_more:true,next_cursor:"synthetic-next",window_start:time,window_end:time})}; }
export async function getProcessingMonitor(token, filters) { if(window.failMonitor) throw new Error('SECRET'); return ${JSON.stringify({items:Array.from({length:6},(_,i)=>({...job,job_id:`00000000-0000-4000-8000-${String(i+1).padStart(12,"0")}`})),has_more:false,window_start:time,window_end:time})}; }`;
const server = await createServer({root, configFile:false, esbuild:{jsx:'automatic'}, resolve:{alias:[{find:'@/lib/api',replacement:'virtual:audit-api'}, {find:'next/link',replacement:'virtual:audit-link'}, {find:'@',replacement:path.join(root,'src')}]}, plugins:[{name:'synthetic-audit-fixture',resolveId(id){if(id.startsWith('virtual:')) return id; if(id==='/audit-preview.tsx') return id;}, load(id){if(id==='virtual:audit-api')return api; if(id==='virtual:audit-link')return `import React from 'react'; export default function Link({children,...props}) { return React.createElement('a',props,children); }`; if(id==='/audit-preview.tsx')return `import React from 'react'; import {createRoot} from 'react-dom/client'; import Audit from '/src/app/admin/audit-logs/audit-logs-client.tsx'; import '/src/app/globals.css'; createRoot(document.getElementById('root')).render(<Audit accessToken="synthetic"/>);`;},configureServer(server){server.middlewares.use((req,res,next)=>{if(req.url==='/'){res.setHeader('Content-Type','text/html');res.end('<html><head><meta name="viewport" content="width=device-width, initial-scale=1"/></head><body><nav style="position:sticky;top:0;z-index:50;height:120px;background:#003366;color:white">Admin</nav><div id="root"></div><script type="module" src="/audit-preview.tsx"></script></body></html>');} else next();});}}],server:{host:'127.0.0.1',port:3061,strictPort:true}});
let browser;
try {
 await server.listen(); browser=await chromium.launch({headless:true});
 const page=await browser.newPage();
 await page.route('**/*',r=>new URL(r.request().url()).hostname==='127.0.0.1'?r.continue():r.abort());
 await page.goto('http://127.0.0.1:3061');
 const results=[];
 for(const [name,width,height] of [['desktop',1280,900],['mobile',390,844]]){
  await page.setViewportSize({width,height});
  await page.waitForFunction(()=>document.querySelectorAll('[aria-label="Scrollable audit events"] tbody tr').length===29);
  await page.waitForFunction(()=>!!document.querySelector('[aria-label="Scrollable audit events"]').style.maxHeight);
  await page.getByRole('region',{name:'Scrollable audit events'}).press('PageDown');
  await page.waitForFunction(()=>document.querySelector('[aria-label="Scrollable audit events"]').scrollTop>0);
  const clearOfNav=await page.getByRole('region',{name:'Scrollable audit events'}).evaluate(el=>{
   const h=innerWidth>=1024?el.previousElementSibling:el.previousElementSibling.previousElementSibling;
   return h.getBoundingClientRect().top>=document.querySelector('nav').getBoundingClientRect().bottom-1;
  });
  if(!clearOfNav)throw Error('List heading obscured by navigation after keyboard focus');
  for(const [position,ratio] of [['top',0],['middle',0.5],['bottom',1]]){
   const data=await page.getByRole('region',{name:'Scrollable audit events'}).evaluate((el,ratio)=>{
    el.scrollTop=(el.scrollHeight-el.clientHeight)*ratio;
    const table=el.querySelector('table'),rows=table.querySelectorAll('tbody tr'),desktop=innerWidth>=1024;
    const header=desktop?el.previousElementSibling:el.previousElementSibling.previousElementSibling;
    const h=header.getBoundingClientRect(),v=el.getBoundingClientRect();
    return {rows:rows.length,overflow:el.scrollWidth-el.clientWidth,pageOverflow:document.documentElement.scrollWidth-document.documentElement.clientWidth,headerBottom:h.bottom,bodyTop:v.top,firstTop:rows[0].getBoundingClientRect().top,scrollTop:el.scrollTop,height:el.clientHeight,fiveHeight:rows[4].getBoundingClientRect().bottom-table.getBoundingClientRect().top,duplicateReferences:[...el.querySelectorAll('[data-label="Resource"]')].some(c=>c.textContent.includes('Reference:'))};
   },ratio);
   if(data.rows!==29||data.overflow>1||data.pageOverflow>1||data.headerBottom>data.bodyTop+1||data.duplicateReferences||(position==='top'&&data.firstTop<data.bodyTop-1)||(name==='desktop'&&Math.abs(data.height-data.fiveHeight)>2))throw Error(JSON.stringify(data));
   results.push({name,position,...data});
   await page.screenshot({path:path.join(output,`${name}-${position}.png`),fullPage:true});
  }
 }
 fs.writeFileSync(path.join(output,'results.json'),JSON.stringify(results,null,2));
 console.log('Five-row top/middle/bottom checks passed at 1280 and 390px.');
}finally{await browser?.close();await server.close();}

// Synthetic-only browser verification of the actual Admin client and stylesheet.
import path from 'node:path';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';
import { createServer } from '../frontend/node_modules/vite/dist/node/index.js';
import { chromium } from '../frontend/node_modules/playwright/index.mjs';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../frontend');
const output = path.resolve(root, '../artifacts/processing-audit');
fs.mkdirSync(output, {recursive:true});
const id = '00000000-0000-0000-0000-000000000001';
const time = '2026-11-02T08:00:00Z';
const job = {job_id:id,status:'failed',attempts:3,created_at:time,confirmed_submissions:1,submission_evidence:'accepted_event',submission_uncertain:false,provider_status:'completed',audio_duration_seconds:18,processing_duration_seconds:12,token_usage:[{event_id:'synthetic-usage',occurred_at:time,prompt_tokens:3,completion_tokens:2,total_tokens:5}],failure:{stage:'extraction',category:'timeout'},actual_cost:null,estimated_cost:null,cost_status:'unknown'};
const audit = {id,occurred_at:time,event_type:'provider.submitted',outcome:'succeeded',actor_type:'system',actor_id:'recording_worker',actor_upn:null,resource_type:'recording_job',resource_id:id,job_id:id,meeting_id:null,correlation_id:id,metadata:{}};
const api = `export class ApiError extends Error {};
export async function getAuditEvents(token, filters) { window.auditQueries ??= []; window.auditQueries.push(filters); return ${JSON.stringify({items:[audit],has_more:false,next_cursor:null,window_start:time,window_end:time})}; }
export async function getProcessingMonitor(token, filters) { if(window.failMonitor) throw new Error('SECRET'); return ${JSON.stringify({items:[job],has_more:false,window_start:time,window_end:time})}; }`;
const server = await createServer({root, configFile:false, esbuild:{jsx:'automatic'}, resolve:{alias:[{find:'@/lib/api',replacement:'virtual:audit-api'}, {find:'next/link',replacement:'virtual:audit-link'}, {find:'@',replacement:path.join(root,'src')}]}, plugins:[{name:'synthetic-audit-fixture',resolveId(id){if(id.startsWith('virtual:')) return id; if(id==='/audit-preview.tsx') return id;}, load(id){if(id==='virtual:audit-api')return api; if(id==='virtual:audit-link')return `import React from 'react'; export default function Link({children,...props}) { return React.createElement('a',props,children); }`; if(id==='/audit-preview.tsx')return `import React from 'react'; import {createRoot} from 'react-dom/client'; import Audit from '/src/app/admin/audit-logs/audit-logs-client.tsx'; import '/src/app/globals.css'; createRoot(document.getElementById('root')).render(<Audit accessToken="synthetic"/>);`;},configureServer(server){server.middlewares.use((req,res,next)=>{if(req.url==='/'){res.setHeader('Content-Type','text/html');res.end('<html><head><meta name="viewport" content="width=device-width, initial-scale=1"/></head><body><div id="root"></div><script type="module" src="/audit-preview.tsx"></script></body></html>');} else next();});}}],server:{host:'127.0.0.1',port:3057,strictPort:true}});
let browser;
try {
 await server.listen();
 browser=await chromium.launch({headless:true});
 const page=await browser.newPage({viewport:{width:1280,height:900}});
 const external=[]; const errors=[];
 page.on('pageerror',error=>{errors.push(error.message);console.log('browser error:',error.message);});
 page.on('console',msg=>{if(msg.type()==='error') console.log('browser console:',msg.text());});
 await page.route('**/*',route=>{if(new URL(route.request().url()).hostname==='127.0.0.1')return route.continue();external.push(route.request().url());return route.abort();});
 await page.goto('http://127.0.0.1:3057');
 await page.getByText('Actual cost: Unknown', {exact:false}).waitFor();
 await page.screenshot({path:path.join(output,'admin-desktop.png'),fullPage:true});
 await page.setViewportSize({width:390,height:844});
 const noOverflow=await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth);
 if(!noOverflow) throw new Error('Narrow screen overflow');
 await page.getByLabel('Job ID',{exact:true}).fill(id);
 await page.getByLabel('Current job status').selectOption('failed');
 await page.getByRole('button',{name:'Apply',exact:true}).click();
 await page.waitForFunction(()=>window.auditQueries?.some(q=>q.status==='failed'&&q.job_id));
 await page.screenshot({path:path.join(output,'admin-390.png'),fullPage:true});
 await page.evaluate(()=>window.failMonitor=true);
 await page.getByRole('button',{name:'Refresh',exact:true}).click();
 await page.getByRole('button',{name:'Retry monitoring'}).waitFor();
 await page.screenshot({path:path.join(output,'admin-error-390.png'),fullPage:true});
 if(await page.getByText('SECRET').count()) throw new Error('Raw error leaked');
 await page.evaluate(()=>window.failMonitor=false);
 await page.getByRole('button',{name:'Retry monitoring'}).click();
 await page.getByText('Actual cost: Unknown',{exact:false}).waitFor();
 if(external.length||errors.length)throw new Error(JSON.stringify({external,errors}));
 fs.writeFileSync(path.join(output,'browser-results.json'),JSON.stringify({synthetic:true,desktop:'1280x900',narrow:'390x844',noOverflow,filters:true,errorRetry:true,externalRequests:external,pageErrors:errors},null,2));
 console.log('Synthetic Admin browser checks passed; desktop/narrow/error screenshots saved.');
} finally { await browser?.close(); await server.close(); }

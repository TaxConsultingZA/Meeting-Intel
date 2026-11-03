// Full Next pages -> real FastAPI -> isolated PostgreSQL. Synthetic identities only.
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {chromium} from '../frontend/node_modules/playwright/index.mjs';
import {expect as baseExpect} from '../frontend/node_modules/@playwright/test/index.mjs';
import {encode} from '../frontend/node_modules/next-auth/jwt.js';
const output=path.resolve('artifacts/meeting-insights');
const fixtures=JSON.parse(await fs.readFile(path.join(output,'release-fixtures.json'),'utf8'));
const API='http://127.0.0.1:8976',WEB='http://127.0.0.1:8975';
const expect=baseExpect.configure({timeout:20000});
const checks=[],external=[],errors=[],responses=[];
const taskName='SYNTHETIC confirmed demo task '+fixtures.ui_id.slice(0,8);
const browser=await chromium.launch({headless:true});
async function userPage(role){
 const upn=fixtures[role];
 const token=await encode({secret:'synthetic-insights-local-session-only',salt:'meeting-intel.session-token.v2',token:{email:upn,name:'Synthetic '+role,accessToken:'mock:'+upn,accessTokenExpires:Date.now()+3600000}});
 const ctx=await browser.newContext({viewport:{width:1440,height:1000}});
 // Do not intercept local JS chunks: Chromium interception truncated a dev chunk at 64 KiB.
 await ctx.route(/^https?:\/\/(?!127\.0\.0\.1(?::|\/)|localhost(?::|\/))/,route=>{external.push(new URL(route.request().url()).origin);return route.abort();});
 await ctx.route('**/_next/static/**',async route=>{const response=await route.fetch();const body=await response.body();return route.fulfill({response,body});});
 await ctx.route('**/api/profile-photo',route=>route.fulfill({status:404,body:''}));
 await ctx.addCookies([{name:'meeting-intel.session-token.v2',value:token,domain:'127.0.0.1',path:'/',httpOnly:true,secure:false,sameSite:'Lax'}]);

 const page=await ctx.newPage();const cdp=await ctx.newCDPSession(page);await cdp.send('Debugger.enable');cdp.on('Debugger.scriptFailedToParse',async event=>{console.log('PARSE FAILURE',JSON.stringify(event));const source=await cdp.send('Debugger.getScriptSource',{scriptId:event.scriptId}).catch(()=>({scriptSource:''}));await fs.writeFile(path.join(output,'parse-failure-source.txt'),source.scriptSource);});page.on('pageerror',e=>{errors.push(e.message);console.log('BROWSER ERROR',e.stack)});page.on('response',r=>{if(r.url().startsWith(API))responses.push({method:r.request().method(),path:r.url().replace(API,''),status:r.status()});});
 return page;
}
async function check(name,run){await run();checks.push({check:name,result:'passed'});console.log('PASS',name);}
async function call(page,role,resource,method='GET',body){return page.request.fetch(API+resource,{method,headers:{Authorization:'Bearer mock:'+fixtures[role]},data:body});}
async function filterMeeting(page){
 await page.getByRole('textbox',{name:'Meeting',exact:true}).fill(fixtures.ui_title);
 await page.getByRole('button',{name:'Apply filters',exact:true}).click();
 await expect(page.getByRole('status').filter({hasText:'Showing 1–1'})).toBeVisible();
}
async function shot(page,name){await page.addStyleTag({content:'body:before{content:"SYNTHETIC DATA ONLY - local Next / FastAPI / isolated PostgreSQL";display:block;background:#fff5c2;color:#17324b;padding:8px 16px;font:12px system-ui}'});await page.screenshot({path:path.join(output,name+'.png'),fullPage:true});}
const page=await userPage('owner');
if(process.argv.includes('--inspect')) {
 const resources=[];page.on('request',r=>resources.push({event:'request',url:r.url(),type:r.resourceType()}));page.on('requestfinished',r=>resources.push({event:'finished',url:r.url()}));page.on('requestfailed',r=>resources.push({event:'failed',url:r.url(),error:r.failure()}));
 try {
 await page.goto(WEB+'/meetings/'+fixtures.ui_id);await page.getByLabel('Analysis summary').waitFor({timeout:30000});console.log('INSPECT initial loaded');
 await page.reload({waitUntil:'networkidle'});await page.getByLabel('Analysis summary').waitFor({timeout:30000});console.log('INSPECT refreshed loaded');
 } finally {await fs.writeFile(path.join(output,'debug-resources.json'),JSON.stringify(resources,null,2));await fs.writeFile(path.join(output,'debug-page.html'),await page.content());await browser.close();}
 process.exit(0);
}
try{
 const url=WEB+'/meetings/'+fixtures.ui_id;
 let source,version;
 await check('Real meeting detail generates a persisted English synthetic draft',async()=>{
   await page.goto(url);
   const panel=page.getByRole('region',{name:'Meeting analysis'});
   await panel.getByRole('button',{name:'Analyze saved transcript (mock)'}).click();
   await panel.getByLabel('Analysis summary').waitFor();
   const result=await call(page,'owner',`/reviews/${fixtures.ui_id}/insights`);assert.equal(result.status(),200);
   const draft=await result.json();assert.equal(draft.status,'awaiting_review');assert.equal(draft.actions.length,3);
   assert(draft.actions.every(i=>i.owner===null&&i.deadline===null&&i.status==='pending_confirmation'));source=draft.actions[0].source_quote;
   await shot(page,'page-generated-draft');
 });
 await check('Edit, confirm one, reject another and leave pending; failed save retains all edits',async()=>{
   const panel=page.getByRole('region',{name:'Meeting analysis'}),fields=panel.locator('fieldset');
   await panel.getByLabel('Analysis summary').fill('SYNTHETIC human-reviewed English summary');
   await fields.nth(0).getByRole('textbox',{name:'Candidate',exact:true}).fill(taskName);
   await fields.nth(0).getByLabel('Owner').fill('owner@example.test');
   await fields.nth(0).getByLabel('Deadline').fill(fixtures.today);
   await fields.nth(0).getByRole('combobox').selectOption('confirmed');
   await fields.nth(1).getByRole('combobox').selectOption('rejected');
   await fields.nth(3).getByRole('textbox',{name:'Candidate',exact:true}).fill('SYNTHETIC reviewed decision: use mock data only');
   await fields.nth(3).getByRole('combobox').selectOption('confirmed');
   // Transport failure only; no stubbed API response or fake persisted state.
   await page.route('**/reviews/*/insights',route=>route.request().method()==='PUT'?route.abort('failed'):route.continue());
   await panel.getByRole('button',{name:'Save review and confirmations'}).click();
   await expect(panel.getByRole('alert')).toContainText('Your edits are retained');
   await expect(panel.getByLabel('Analysis summary')).toHaveValue('SYNTHETIC human-reviewed English summary');
   await expect(fields.nth(0).getByRole('combobox')).toHaveValue('confirmed');
   await shot(page,'page-save-failure-retains-draft');
   await page.unroute('**/reviews/*/insights');
   await panel.getByRole('button',{name:'Save review and confirmations'}).click();
   await expect(panel.getByText('Analysis: awaiting_review · Version 2')).toBeVisible();
   await expect(fields.nth(0).getByRole('textbox',{name:'Candidate',exact:true})).toBeDisabled();
   const draft=await (await call(page,'owner',`/reviews/${fixtures.ui_id}/insights`)).json();version=draft.version;assert.equal(version,2);
 });
 await check('Refresh restores human edits and independent confirmation without approving meeting notes',async()=>{
   await page.reload({waitUntil:'networkidle'});
   const panel=page.getByRole('region',{name:'Meeting analysis'});
   await expect(panel.getByLabel('Analysis summary')).toHaveValue('SYNTHETIC human-reviewed English summary');
   await expect(panel.locator('fieldset').nth(0).getByRole('combobox')).toHaveValue('confirmed');
   await expect(panel.locator('fieldset').nth(1).getByRole('combobox')).toHaveValue('rejected');
   await expect(panel.locator('fieldset').nth(2).getByRole('combobox')).toHaveValue('pending_confirmation');
   await expect(panel.locator('fieldset').nth(3).getByRole('textbox',{name:'Candidate',exact:true})).toHaveValue('SYNTHETIC reviewed decision: use mock data only');
   const meeting=await (await call(page,'owner',`/reviews/${fixtures.ui_id}`)).json();assert.equal(meeting.state,'awaiting_review');assert.equal(meeting.summary,'Saved original notes - synthetic only');
   await shot(page,'page-refreshed-confirmation');
 });
 await check('Action Items shows only confirmed action with pending note status and existing task management',async()=>{
   await page.getByRole('link',{name:'Action Items',exact:true}).click();
   await page.waitForURL(WEB+'/action-items');await filterMeeting(page);
   const row=page.getByRole('row').filter({hasText:taskName});
   await row.waitFor();
   await expect(row).toContainText('Action: human confirmed');await expect(row).toContainText('Meeting notes: not approved');await expect(row).toContainText('Open');
   await row.getByText('View source evidence').click();await expect(row).toContainText(source);
   const data=await (await call(page,'owner','/action-items?view=all')).json();
   const items=data.items.filter(i=>i.meeting_id===fixtures.ui_id);assert.equal(items.length,1);assert.equal(items[0].can_complete,true);assert.equal(items[0].meeting_notes_approved,false);
   await expect(page.getByLabel('Personal action item due reminders')).toContainText(taskName);
   await shot(page,'page-action-items-open');
   await row.getByRole('button',{name:/Mark complete/}).click();await expect(row.getByRole('button',{name:/Reopen/})).toBeVisible();
   await expect(page.getByLabel('Personal action item due reminders')).toHaveCount(0);
   await page.reload({waitUntil:'networkidle'});const reloaded=page.getByRole('row').filter({hasText:taskName});await expect(reloaded).toContainText('Completed');
   await reloaded.getByRole('button',{name:/Reopen/}).click();await expect(reloaded.getByRole('button',{name:/Mark complete/})).toBeVisible();
   await expect(page.getByLabel('Personal action item due reminders')).toContainText(taskName);
   await page.getByRole('button',{name:'Dismiss these reminders for today'}).click();
   await expect(page.getByLabel('Personal action item due reminders')).toHaveCount(0);
   await page.getByRole('button',{name:'Refresh',exact:true}).click();
   await expect(page.getByRole('button',{name:'Refresh',exact:true})).toBeEnabled();
   await expect(page.getByLabel('Personal action item due reminders')).toHaveCount(0);
   await page.getByRole('button',{name:'Restore dismissed reminders'}).click();
   await expect(page.getByLabel('Personal action item due reminders')).toContainText(taskName);
 });
 await check('Readonly participant can read detail and action status but cannot edit or complete',async()=>{
   const viewer=await userPage('viewer');await viewer.goto(url);
   const panel=viewer.getByRole('region',{name:'Meeting analysis'});
   await expect(panel.getByLabel('Analysis summary')).toBeDisabled();
   assert.equal(await panel.getByRole('button',{name:'Save review and confirmations'}).count(),0);
   const body=await (await call(viewer,'viewer',`/reviews/${fixtures.ui_id}/insights`)).json();
   assert.equal((await call(viewer,'viewer',`/reviews/${fixtures.ui_id}/insights`,'PUT',body)).status(),403);
   await shot(viewer,'page-viewer-readonly');await viewer.getByRole('link',{name:'Action Items',exact:true}).click();await filterMeeting(viewer);
   const row=viewer.getByRole('row').filter({hasText:taskName});await row.waitFor();assert.equal(await row.getByRole('button').count(),0);
   await shot(viewer,'page-viewer-action-items');
 });
 await check('390px pages keep controls visible without document overflow; action table scrolls locally',async()=>{
   await page.setViewportSize({width:390,height:844});await page.goto(url);
   await page.getByRole('region',{name:'Meeting analysis'}).getByLabel('Analysis summary').waitFor();
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
   await shot(page,'page-mobile-detail');
   await page.getByRole('link',{name:'Action Items',exact:true}).click();await filterMeeting(page);await page.getByRole('row').filter({hasText:taskName}).waitFor();
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
   const table=page.getByRole('table');assert(await table.evaluate(e=>e.parentElement.scrollWidth>e.parentElement.clientWidth));
   await shot(page,'page-mobile-action-items');
 });
 assert.deepEqual(external,[]);assert.deepEqual(errors,[]);assert.equal(responses.filter(r=>r.status>=500).length,0);
 assert(!responses.some(r=>/approve|reprocess|send-copy/.test(r.path)));
} catch(error){await shot(page,'page-failure-debug');throw error;}
finally{
 await fs.writeFile(path.join(output,'release-browser-results.json'),JSON.stringify({checks,external,errors,responses},null,2));
 await browser.close();
}

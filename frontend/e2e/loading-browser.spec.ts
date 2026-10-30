import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
test.skip(process.env.LOADING_REVIEW_FIXTURE !== 'true', 'Requires the isolated loopback fixture servers.');
const out = path.resolve(__dirname, '../../artifacts/local-test-recordings/loading-review');
const measurements: unknown[] = [];
test('after: synthetic job transitions queued processing completed and failed', async ({page}) => {
 let phase='queued';
 await page.route('**/recordings/jobs?**', async route=>{
  await route.fulfill({json:[{job_id:'synthetic-transition',drive_item_id:'queued',meeting_id:'queued',title:'Synthetic transition',status:phase==='queued'?'pending':phase,processing_status:phase,phase,review_status:phase==='completed'?'awaiting_review':null,attempts:phase==='queued'?0:1,max_attempts:3,error:null,can_retry:false,can_cancel:false,can_reprocess:false,processing_enabled:true,auto_processing_admitted:true}]});
 });
 for(const terminal of ['completed','failed']) {
  phase='queued';
  await page.goto('http://127.0.0.1:3044/meetings/queued');
  const region=page.getByRole('region',{name:'Recording processing',exact:true});
  await expect(region.getByText('Queued',{exact:true})).toBeVisible();
  for(const next of ['processing',terminal]) {
   phase=next;
   await region.getByRole('button',{name:'Refresh status',exact:true}).click();
   await expect(region.getByText(next[0].toUpperCase()+next.slice(1),{exact:true})).toBeVisible();
   await page.screenshot({path:path.join(out,`job-transition-${next}.png`),fullPage:true});
  }
 }
});
test('after: original Chinese, unknown voices and transcript-only review on narrow screens', async ({page}) => {
 await page.goto('http://127.0.0.1:3044/meetings/language');
 await expect(page.getByText('Transcript ready.', {exact:true})).toBeVisible();
 await expect(page.getByRole('combobox', {name:'Name for Speaker A'})).toHaveValue('');
 await expect(page.getByText(/Unknown \/ Guest means the voice has not been identified/)).toBeVisible();
 await expect(page.getByText(/这是合成中文测试内容/)).toBeVisible();
 await expect(page.getByText('No meeting summary is available.',{exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:/Approve Meeting Notes/})).toBeVisible();
 await expect(page.getByText('Synthetic decision',{exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'Refresh status',exact:true})).toBeEnabled();
 await page.screenshot({path:path.join(out,'original-language-desktop.png'),fullPage:true});
 await page.setViewportSize({width:390,height:844});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:path.join(out,'original-language-390.png'),fullPage:true});
 const mutations: string[]=[];
 page.on('request', request=>{if(request.method()!=='GET') mutations.push(request.method()+' '+new URL(request.url()).pathname);});
 await page.getByRole('button',{name:'Preview Email',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Email Preview',exact:true})).toBeVisible();
 await expect(page.getByText('Meeting Notes — Synthetic transcript-only review',{exact:true})).toBeVisible();
 await expect(page.frameLocator('iframe[title="Meeting notes email preview"]').getByText(/without AI summary or action-item extraction/)).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 const emailContent=page.getByRole('region',{name:'Email content preview',exact:true});
 expect(await emailContent.evaluate(el=>el.scrollWidth>el.clientWidth)).toBe(true);
 await page.screenshot({path:path.join(out,'transcript-only-email-preview.png'),fullPage:true});
 await page.getByRole('button',{name:'Close Preview',exact:true}).click();
 await page.getByRole('button',{name:/Approve Meeting Notes/}).click();
 await expect(page.getByText(/Approval locks the current notes/)).toBeVisible();
 await expect(page.getByRole('button',{name:'Approve Meeting Notes',exact:true})).toBeEnabled();
 await page.screenshot({path:path.join(out,'transcript-only-approval-review.png'),fullPage:true});
 await page.getByRole('button',{name:'Cancel',exact:true}).click();
 expect(mutations).toEqual([]);
 const transcript = page.getByRole('heading',{name:'Transcript',exact:true}).locator('../..');
 await transcript.getByRole('button',{name:'Edit',exact:true}).click();
 const draft=page.getByRole('textbox',{name:'Meeting transcript'});
 await draft.fill('[Speaker A] 合成未保存逐字稿草稿');
 await page.getByRole('button',{name:'Refresh status',exact:true}).click();
 await expect(draft).toHaveValue('[Speaker A] 合成未保存逐字稿草稿');
 await page.screenshot({path:path.join(out,'transcript-draft-after-refresh.png'),fullPage:true});
});
for (const [variant,port] of [['before',3043],['after',3044]] as const) {
 test(`${variant}: measure warm dashboard and detail requests`, async ({page}) => {
  const requests: unknown[]=[];
  page.on('requestfinished',r=>{ const t=r.timing(); requests.push({method:r.method(),path:new URL(r.url()).pathname,ms:Math.round(t.responseEnd),responseStart:Math.round(t.responseStart)}); });
  await page.goto(`http://127.0.0.1:${port}/meetings/completed`);
  await expect(page.getByText('Synthetic saved summary.',{exact:false})).toBeVisible();
  await page.goto(`http://127.0.0.1:${port}/`);
  await expect(page.getByRole('button',{name:'Process Past Recording'})).toBeVisible();
  const start=Date.now();
  await page.goto(`http://127.0.0.1:${port}/meetings/completed`,{waitUntil:'commit'});
  await expect(page.locator('nav').first()).toBeVisible();
  const nav=Date.now()-start;
  if(variant==='after') {
   await expect(page.getByRole('heading',{name:'Meeting details',exact:true})).toBeVisible();
   await page.screenshot({path:path.join(out,'after-slow-detail.png'),fullPage:true});
  }
  await expect(page.getByText('Synthetic saved summary.',{exact:false})).toBeVisible();
  const content=Date.now()-start;
  await expect(page.getByText('Synthetic decision',{exact:true})).toBeVisible({timeout:10000});
  const decisions=Date.now()-start;
  await page.screenshot({path:path.join(out,`${variant}-detail.png`),fullPage:true});
  const homeStart=Date.now();
  await page.goto(`http://127.0.0.1:${port}/`,{waitUntil:'commit'});
  await expect(page.getByRole('button',{name:'Process Past Recording'})).toBeVisible();
  const homeShell=Date.now()-homeStart;
  await page.getByRole('button',{name:'In Progress',exact:true}).click();
  await expect(page.getByText(/Processing is paused for this environment/).first()).toBeVisible();
  const homeContent=Date.now()-homeStart;
  measurements.push({variant,nav_ms:nav,content_ms:content,decisions_ms:decisions,home_shell_ms:homeShell,home_queue_ms:homeContent,requests});
  fs.writeFileSync(path.join(out,'browser-timings.json'),JSON.stringify(measurements,null,2));
 });
}
test('after: states, duplicate clicks, narrow screen and error retry',async({page,request})=>{
 await request.get('http://127.0.0.1:8044/__fixture?reset=true');
 await page.goto('http://127.0.0.1:3044/');
 await page.getByRole('button',{name:'Process Past Recording'}).click();
 await expect(page.getByText('Recording list and task status loaded successfully.')).toBeVisible();
 await expect(page.getByRole('button',{name:'Transcribe'})).toHaveCount(1);
 await expect(page.getByRole('button',{name:'Cancel',exact:true})).toHaveCount(1);
 await expect(page.getByRole('button',{name:'Retry',exact:true})).toHaveCount(1);
 await expect(page.getByRole('link',{name:'View',exact:true})).toHaveCount(3);
 await page.screenshot({path:path.join(out,'recording-states.png'),fullPage:true});
 const transcribe=page.getByRole('button',{name:'Transcribe'});
 await transcribe.evaluate((button:HTMLButtonElement)=>{button.click();button.click();});
 await expect(page.getByRole('button',{name:'Transcribe'})).toHaveCount(0);
 await expect(page.getByRole('button',{name:'Cancel',exact:true})).toHaveCount(2);
 expect((await (await request.get('http://127.0.0.1:8044/__fixture')).json()).posts).toBe(1);
 await page.setViewportSize({width:390,height:844});
 await page.screenshot({path:path.join(out,'recordings-narrow.png'),fullPage:true});
 await expect(page.getByRole('button',{name:'Close recording dialog'})).toBeVisible();
 await page.getByRole('button',{name:'Close recording dialog'}).click();
 await page.goto('http://127.0.0.1:3044/meetings/completed',{waitUntil:'commit'});
 await page.screenshot({path:path.join(out,'detail-narrow-loading.png'),fullPage:true});
 await expect(page.getByText('Synthetic saved summary.',{exact:false})).toBeVisible();
 await page.screenshot({path:path.join(out,'detail-narrow.png'),fullPage:true});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.goto('http://127.0.0.1:3044/meetings/error');
 await expect(page.getByRole('button',{name:'Retry loading meeting'})).toBeVisible();
 await expect(page.locator('nav')).toBeVisible();
 await page.screenshot({path:path.join(out,'detail-error.png'),fullPage:true});
 await request.get('http://127.0.0.1:8044/__fixture?error=false');
 await page.getByRole('button',{name:'Retry loading meeting'}).click();
 await expect(page.getByText('Synthetic saved summary.',{exact:false})).toBeVisible();
});



test('after: status refresh keeps the Decisions editor and unsaved draft mounted',async({page})=>{
 await page.goto('http://127.0.0.1:3044/meetings/completed');
 await expect(page.getByText('Synthetic decision',{exact:true})).toBeVisible({timeout:10000});
 await page.getByRole('button',{name:'Edit decisions',exact:true}).click();
 const draft=page.getByRole('textbox',{name:'Decision 1 content'});
 await draft.fill('Unsaved local draft — 保留内容');
 await draft.evaluate(el=>el.setAttribute('data-test-editor-identity','same-editor'));
 const response=page.waitForResponse(r=>r.url().includes('/recordings/jobs'));
 await page.getByRole('button',{name:'Refresh status',exact:true}).click();
 await response;
 await expect(draft).toHaveValue('Unsaved local draft — 保留内容');
 await expect(draft).toHaveAttribute('data-test-editor-identity','same-editor');
 await page.screenshot({path:path.join(out,'decisions-draft-after-refresh.png'),fullPage:true});
});



test('after: loading shell matches navigation styling and respects reduced motion',async({page})=>{
 await page.emulateMedia({reducedMotion:'reduce'});
 for(const width of [1365,390]) {
  await page.setViewportSize({width,height:900});
  await page.goto('http://127.0.0.1:3044/meetings/completed',{waitUntil:'commit'});
  await expect(page.getByRole('heading',{name:'Meeting details',exact:true})).toBeVisible();
  await expect(page.getByRole('link',{name:'Dashboard',exact:true})).toBeVisible();
  const loading=page.getByRole('main',{name:'Meeting detail loading'});
  const animation=await loading.locator('.motion-safe\\:animate-pulse').first().evaluate(el=>getComputedStyle(el).animationName);
  expect(animation).toBe('none');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:path.join(out,`final-loading-${width}.png`),fullPage:true});
  await expect(page.getByText('Synthetic saved summary.',{exact:false})).toBeVisible();
 }
});

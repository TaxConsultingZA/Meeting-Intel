import json,subprocess
from pathlib import Path
import shutil
repo=Path(__file__).resolve().parents[1]
out=repo/'artifacts/local-test-recordings/loading-review'
out.mkdir(parents=True,exist_ok=True)
for variant,port in [('before',3043),('after',3044)]:
 target=out/variant
 shutil.copytree(repo/'frontend',target,dirs_exist_ok=True,ignore=shutil.ignore_patterns('node_modules','.next','.env*','test-results','playwright-report','AGENTS.md','CLAUDE.md'))
 if variant=='before':
  for file in ['page.tsx','loading.tsx']:
   (target/'src/app/meetings/[id]'/file).write_bytes(subprocess.check_output(['git','show',f'HEAD:frontend/src/app/meetings/[id]/{file}'],cwd=repo))
 (target/'src/lib/auth.ts').write_text('export async function auth() { await new Promise(r=>setTimeout(r,150)); return {user:{email:"owner@example.com"},accessToken:"synthetic-local-token",authError:null}; }\nexport const handlers = {GET:()=>new Response("{}"),POST:()=>new Response("{}")};\n',encoding='utf-8')
 (target/'.env.local').write_text('NEXT_PUBLIC_API_URL=http://127.0.0.1:8044\nAUTH_URL=http://localhost:'+str(port)+'\n',encoding='utf-8')
 (target/'src/app/api/profile-photo/route.ts').write_text('export async function GET(){return new Response(\'<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"><text x="11" y="21" fill="%23003366">O</text></svg>\',{headers:{"Content-Type":"image/svg+xml"}});}',encoding='utf-8')
 subprocess.run(['powershell','-NoProfile','-Command',f"if (-not (Test-Path -LiteralPath '{target}/node_modules')) {{ New-Item -ItemType Junction -Path '{target}/node_modules' -Target '{repo}/frontend/node_modules' | Out-Null }}"],check=True)
print('Isolated synthetic frontend copies refreshed; no production configuration copied.')

"""Loopback-only synthetic UI fixture API. Never loads app settings or credentials."""
import json,time,threading
import runpy
from types import SimpleNamespace
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlparse,parse_qs
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/'artifacts/local-test-recordings/loading-review'
build_email=runpy.run_path(str(Path(__file__).resolve().parents[1]/'app/email_templates.py'))['build_meeting_email']
state={'error':True,'posts':0,'imported':False}
def meeting(id='completed'):
 return dict(id=id,title='[Synthetic] 与 Wei 的会议',state={'queued':'queued','failed':'failed'}.get(id,'awaiting_review'),summary=None if id=='language' else 'Synthetic saved summary. Review this recording before approval.',transcript=('[Speaker A] '+ '这是合成中文测试内容，保留原文，不自动翻译。'*35+'\n[Speaker B] Synthetic guest voice; identity unconfirmed.') if id=='language' else '[Speaker A] Synthetic transcript for local browser verification.',action_items=[],extracted_json={'extraction_mode':'transcript_only'},calendar_participants=[],organizer_upn='owner@example.com',recorded_at='2026-10-22T06:50:31Z',email_recipients=[],approved_recipients=[],is_organizer=True,can_edit=True,can_approve=True,can_request_edit_access=False,edit_access_status='organizer',edit_access_requests=[],speaker_candidates=[],speaker_mappings={},speaker_sample_labels=['Speaker A','Speaker B'] if id=='language' else [],recording_display={'filename':'与 Wei 的会议-20261022_145031-会议记录.mp4','association_status':'independent','identity_reason':None},failure={'stage':'transcription','category':'timeout'} if id=='failed' else None)
def jobs():
 return [dict(job_id=i,drive_item_id=i,meeting_id=i,title=i+'.mp4',recording_filename=i+'.mp4',recording_identity_verified=True,status=s,processing_status=p,phase=p,review_status='awaiting_review' if s=='completed' else None,attempts=1 if s!='pending' else 0,max_attempts=3,error=None,can_retry=s=='failed',can_cancel=s=='pending',can_reprocess=False,processing_enabled=False) for i,s,p in [('queued','pending','queued'),('completed','completed','completed'),('failed','failed','failed')] + ([('new','pending','queued')] if state['imported'] else [])]
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args): pass
 def respond(self,data,status=200):
  self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Access-Control-Allow-Origin','*');self.send_header('Access-Control-Allow-Headers','Authorization,Content-Type');self.send_header('Access-Control-Allow-Methods','GET,POST,PUT,OPTIONS');self.end_headers();self.wfile.write(json.dumps(data).encode())
 def do_OPTIONS(self): self.respond({})
 def do_GET(self):
  start=time.perf_counter();u=urlparse(self.path);p=u.path;q=parse_qs(u.query);status=200
  if p=='/__fixture':
   if 'error' in q:state['error']=q['error'][0]=='true'
   if 'reset' in q:state.update(error=True,posts=0,imported=False)
   self.respond(state);return
  if p=='/users/me':time.sleep(.4);data=dict(id='synthetic',upn='owner@example.com',is_admin=False,is_subscribed=True)
  elif p=='/recordings/jobs':
   time.sleep(.3);data=[j for j in jobs() if not q.get('meeting_id') or j['meeting_id']==q['meeting_id'][0]]
  elif p=='/recordings/available': data=[dict(drive_item_id=i,drive_id='synthetic-drive',name=i+'.mp4',size=1048576,created_at='2026-10-22T06:50:31Z',already_imported=i!='new' or state['imported'],meeting_id=i if i!='new' else None,meeting_state=meeting(i)['state'] if i!='new' else None,calendar_matched=False) for i in ['new','queued','completed','failed']]
  elif p=='/recordings/update':data=[dict(stage=s,status='success',counts={},error=None,last_attempted_at=None,last_succeeded_at=None) for s in ['calendar','discovery','matching']]
  elif p.endswith('/email-preview'):
   subject,html=build_email(SimpleNamespace(title='Synthetic transcript-only review',organizer_upn='owner@example.test',recorded_at=None,summary=None,extracted_json={'extraction_mode':'transcript_only'},action_items=[]))
   data=dict(subject=subject,html=html,recipients=[],fingerprint='synthetic-preview')
  elif p in ['/reviews/all','/reviews/pending']:time.sleep(.5);data=[meeting(i) for i in ['queued','completed','failed']]
  elif p.startswith('/reviews/') and p.endswith('/decisions'):time.sleep(3);data=[dict(id='decision',meeting_id=p.split('/')[2],content='Synthetic decision',decision_date='2026-10-22',sort_order=0,created_at=None,updated_at=None)]
  elif p.startswith('/reviews/') and p.count('/')==2 and p not in ['/reviews/historical']:
   time.sleep(2);id=p.split('/')[-1];status=503 if id=='error' and state['error'] else 200;data=meeting(id) if status==200 else {'detail':'Synthetic unavailable'}
  else:data=[]
  self.respond(data,status)
  with (ROOT/'fixture-requests.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps({'method':'GET','path':p,'status':status,'ms':round((time.perf_counter()-start)*1000)})+'\n')
 def do_POST(self):
  state['posts']+=1
  if self.path=='/recordings/import':time.sleep(1);state['imported']=True
  self.respond({'ok':True,'queued':True,'status':'pending'})
ThreadingHTTPServer(('127.0.0.1',8044),Handler).serve_forever()


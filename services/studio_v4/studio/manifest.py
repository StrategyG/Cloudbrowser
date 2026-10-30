"""Deterministic fail-closed prompt planner; never represent keyword matching as AI inference."""
import re
from typing import Literal
from pydantic import BaseModel, Field, model_validator
from .settings import MAX_DURATION_SECONDS, MAX_TOTAL_FRAMES

class Shot(BaseModel):
 character: str = Field(min_length=1,max_length=70,pattern=r'^[A-Za-z0-9_-]+$')
 action: Literal['idle','walk','wave','jump']
 duration: float=Field(ge=0.5,le=MAX_DURATION_SECONDS)
 location: Literal['studio','arusia','forest']='studio'
 lighting: Literal['neutral','sunset','warm','night']='neutral'
 camera: Literal['static','orbit','closeup']='static'

class Manifest(BaseModel):
 version: Literal['1.0']='1.0'
 fps: Literal[24,30,60]=24
 width: Literal[640,1280,1920]=1280
 height: Literal[360,720,1080]=720
 shots: list[Shot]=Field(min_length=1,max_length=12)
 approval: Literal['pending','approved']='pending'
 planner: Literal['rules_v1','structured_user','local_qwen']='rules_v1'
 @model_validator(mode='after')
 def validate_timing(self):
  if (self.width,self.height) not in {(640,360),(1280,720),(1920,1080)}:
   raise ValueError('Unsupported aspect ratio')
  if sum(s.duration for s in self.shots)>MAX_DURATION_SECONDS:
   raise ValueError(f'Combined shot duration cannot exceed {MAX_DURATION_SECONDS} s')
  if len({s.character for s in self.shots})!=1:
   raise ValueError('Current renderer supports one character per manifest')
  if round(sum(s.duration for s in self.shots)*self.fps)>MAX_TOTAL_FRAMES:
   raise ValueError('Frame quota exceeded')
  return self

_ACTIONS={
 'walk': ('berjalan','melangkah','walk','jalan'),
 'wave': ('melambaikan','melambai','menyapa','wave','lambai'),
 'jump': ('melompat','lompat','jump'),
 'idle': ('diam','berhenti','idle','berdiri','stand'),
}

def plan(text, fps=24, character='KIO', width=1280, height=720):
 """Simple parser; unsupported verbs fail instead of manufacturing a plausible animation."""
 if not text or len(text)>1200: raise ValueError('Prompt must contain 1–1200 characters')
 t=text.casefold(); sep=re.split(r'\b(?:kemudian|lalu|setelah itu|then|and then)\b|[;]',t)
 duration_match=re.search(r'\b(\d+(?:[.,]\d+)?)\s*(?:detik|seconds?|sec|s)\b',t)
 duration=float(duration_match.group(1).replace(',','.')) if duration_match else 5.0
 if duration>MAX_DURATION_SECONDS or duration<0.5: raise ValueError('Duration outside supported range')
 loc='arusia' if 'arusia' in t else ('forest' if any(k in t for k in ('forest','hutan')) else 'studio')
 light='sunset' if any(k in t for k in ('sunset','senja')) else ('night' if any(k in t for k in ('night','malam')) else ('warm' if 'warm' in t else 'neutral'))
 cam='orbit' if 'orbit' in t else ('closeup' if any(k in t for k in ('zoom','closeup')) else 'static')
 acts=[]
 for part in sep:
  detected=[(a,min((part.find(k) for k in keys if k in part),default=10**9)) for a,keys in _ACTIONS.items()]
  found=sorted([x for x in detected if x[1]<10**9],key=lambda x:x[1])
  if found: acts.append(found[0][0])
 if not acts: raise ValueError('No supported action detected; choose idle/walk/wave/jump or supply structured manifest')
 if len(acts)>6: raise ValueError('Too many actions for quick planner')
 dur=duration/len(acts)
 shots=[Shot(character=character,action=a,duration=dur,location=loc,lighting=light,camera=cam) for a in acts]
 return Manifest(fps=fps,width=width,height=height,shots=shots,planner='rules_v1')

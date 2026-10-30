"""Optional *local* llama.cpp OpenAI-compatible planner for Qwen GGUF.
The model may suggest a shot manifest; Pydantic validation and human approval are mandatory.
"""
import json
import os
from urllib.request import Request, urlopen
from urllib.parse import urlparse
from .manifest import Manifest

SYSTEM_PROMPT='''You are a bounded animation shot planner, not a video generator.
Return exactly one JSON object with fields: version, fps, width, height, shots, approval, planner.
Do not invent unsupported actions. Each shot has character, action, duration, location, lighting, camera.
Allowed action: idle, walk, wave, jump.
Allowed location: studio, arusia, forest.
Allowed lighting: neutral, sunset, warm, night.
Allowed camera: static, orbit, closeup.
Total duration <=15 sec, max 12 shots. The user asks for a single named character.
All shots must have the provided character. Return approval='pending', planner='local_qwen'.
Never claim that files or videos were produced.
'''

def generate(prompt, fps=24, character='KIO', width=1280, height=720):
 url=os.getenv('LLAMA_CPP_URL','')
 if not url: raise RuntimeError('LLAMA_CPP_URL not configured: run a local Qwen GGUF llama.cpp server')
 parts=urlparse(url)
 if parts.scheme!='http' or not parts.hostname or parts.path!='/v1/chat/completions':
  raise RuntimeError('LLAMA_CPP_URL must be an HTTP llama.cpp /v1/chat/completions endpoint')
 # URL is environment configuration, never a client-provided URL.
 body={'model':os.getenv('LLAMA_CPP_MODEL','local-qwen'),
       'temperature':0,'max_tokens':1400,
       'messages':[{'role':'system','content':SYSTEM_PROMPT},
                   {'role':'user','content':f'Character: {character}\nFPS: {fps}\nResolution: {width}x{height}\nPrompt: {prompt}'}],
       'response_format':{'type':'json_object'}}
 request=Request(url,data=json.dumps(body).encode(),headers={'Content-Type':'application/json'},method='POST')
 with urlopen(request,timeout=40) as reply:
  raw=reply.read(128_000).decode('utf-8')
 content=json.loads(raw)['choices'][0]['message']['content'].strip()
 if content.startswith('```'):
  content=content.removeprefix('```json').removeprefix('```').removesuffix('```').strip()
 candidate=json.loads(content)
 candidate['planner']='local_qwen';candidate['approval']='pending'
 candidate['fps']=fps;candidate['width']=width;candidate['height']=height
 manifest=Manifest.model_validate(candidate)
 if any(s.character!=character for s in manifest.shots):raise ValueError('LLM changed character')
 return manifest

"""Run exactly one worker per shared SQLite workspace. Durable jobs outlive the API process."""
import logging
import fcntl
import time
from . import store
from .pipeline import run_job

logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')

def run_forever():
 store.init()
 lease=(store.DATA_ROOT/'worker.lock').open('a')
 try:fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
 except BlockingIOError:raise RuntimeError('A Studio worker already owns this workspace') from None
 # A hard crash may leave the worker-owned running job unclaimed; retry once on startup.
 with store.conn() as db:
  db.execute("UPDATE jobs SET state='queued' WHERE state='running' AND attempts<2")
  db.execute("UPDATE jobs SET state='failed',message='Manual recovery required' WHERE state='running' AND attempts>=2")
  dead=db.execute("SELECT DISTINCT project_id FROM jobs WHERE state='failed' AND message='Manual recovery required'").fetchall()
  for row in dead:
   db.execute("UPDATE projects SET state='failed',updated_at=? WHERE id=? AND state IN ('mesh_building','rig_building','rendering')",(time.time(),row['project_id']))
 logging.info('Studio worker started')
 while True:
  task=store.claim_job()
  if task:
   logging.info('Executing job %s / %s',task['id'],task['kind'])
   run_job(task)
  else:time.sleep(1)

if __name__=='__main__':run_forever()

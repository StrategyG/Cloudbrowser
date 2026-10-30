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
 # The OS file lease ensures only the sole worker reconciles its previous run.
 # Do not replay a potentially executed render/mesh job without owner inspection.
 interrupted=store.recover_interrupted()
 logging.info('Studio worker started; %d interrupted jobs require manual review',interrupted)
 while True:
  task=store.claim_job()
  if task:
   logging.info('Executing job %s / %s',task['id'],task['kind'])
   run_job(task)
  else:time.sleep(1)

if __name__=='__main__':run_forever()

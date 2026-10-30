"""Godot fixed-FPS movie renderer. No shell evaluation or arbitrary filesystem paths."""
import json, os, shutil, subprocess, tempfile
from pathlib import Path
from .core import ROOT, get_project, transition

GODOT = os.getenv('GODOT_BIN','godot')
FFMPEG = os.getenv('FFMPEG_BIN','ffmpeg')
FFPROBE = os.getenv('FFPROBE_BIN','ffprobe')
TEMPLATE = Path(__file__).resolve().parent.parent/'godot'


def run(args, *, timeout):
    try:
        p=subprocess.run(args,capture_output=True,text=True,timeout=timeout,check=False)
    except (OSError,subprocess.TimeoutExpired) as e:
        raise RuntimeError(f'External tool failure: {type(e).__name__}') from e
    if p.returncode:
        raise RuntimeError(f'{Path(args[0]).name} exited {p.returncode}: {p.stderr[-1000:]}')
    return p.stdout


def probe(path):
    data=json.loads(run([FFPROBE,'-v','error','-select_streams','v:0',
                         '-show_entries','stream=codec_name,width,height,r_frame_rate,nb_frames',
                         '-of','json',str(path)],timeout=30))
    if not data.get('streams'): raise RuntimeError('No video stream')
    return data['streams'][0]


def render(pid):
    project=get_project(pid)
    if project['state']!='claimed': raise ValueError('Job is not claimed')
    transition(pid,{'claimed'},'rendering')
    directory=ROOT/pid
    data=project['manifest']
    frames=round(data['fps']*data['duration'])
    try:
        with tempfile.TemporaryDirectory(prefix='godot_',dir=directory) as d:
            workspace=Path(d)
            shutil.copytree(TEMPLATE,workspace/'project')
            game=workspace/'project'
            shutil.copy(directory/'actor.glb',game/'actor.glb')
            (game/'manifest.json').write_text(json.dumps(data),encoding='utf-8')
            run([GODOT,'--headless','--editor','--path',str(game),'--import','--quit'],timeout=120)
            movie=workspace/'shot.avi'
            env_prefix=['xvfb-run','-a','-s','-screen 0 1280x720x24'] if os.getenv('USE_XVFB','1')=='1' else []
            run(env_prefix+[GODOT,'--path',str(game),'--rendering-method','gl_compatibility',
                  '--resolution',f"{data['width']}x{data['height']}",
                  '--write-movie',str(movie),'--fixed-fps',str(data['fps']),
                  '--quit-after',str(frames),'--disable-vsync'],timeout=900)
            if not movie.is_file() or movie.stat().st_size < 512:
                raise RuntimeError('Godot did not produce video')
            input_info=probe(movie)
            if (int(input_info.get('width',0)),int(input_info.get('height',0))) != (data['width'],data['height']):
                raise RuntimeError('Incorrect Godot video resolution')
            tmp=workspace/'output.mp4'
            run([FFMPEG,'-hide_banner','-loglevel','error','-y','-i',str(movie),
                 '-an','-c:v','libx264','-pix_fmt','yuv420p','-r',str(data['fps']),
                 '-movflags','+faststart',str(tmp)],timeout=900)
            info=probe(tmp)
            if info.get('codec_name')!='h264' or (int(info.get('width',0)),int(info.get('height',0))) != (data['width'],data['height']):
                raise RuntimeError('MP4 failed codec or dimension validation')
            if info.get('nb_frames','N/A') not in ('N/A',str(frames)):
                raise RuntimeError('MP4 frame count mismatch')
            os.replace(tmp,directory/'output.mp4')
        transition(pid,{'rendering'},'completed')
    except Exception as exc:
        transition(pid,{'rendering'},'failed',error=str(exc)[:1000])
        raise


def run_worker(*,once=False):
    import time
    from .core import connection
    while True:
        with connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute("SELECT id FROM projects WHERE state='queued' ORDER BY updated LIMIT 1").fetchone()
            if row:
                db.execute("UPDATE projects SET state='claimed',updated=? WHERE id=? AND state='queued'",(time.time(),row['id']))
            db.commit()
        if row:
            pid=row['id']
            try:
                render(pid)
            except Exception as exc:
                print('Render failed:',pid,type(exc).__name__,str(exc)[:200],flush=True)
        if once: return
        time.sleep(2)

if __name__=='__main__':
    run_worker()

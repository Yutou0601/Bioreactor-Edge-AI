# -*- coding: utf-8 -*-
"""研究實驗排程 API（前端「實驗排程」頁）。邏輯全在 core/research_jobs.py。"""
from fastapi import APIRouter, Body, HTTPException, Query

from core import research_jobs as RJ

router = APIRouter()


def _call(fn, *a, **kw):
    try:
        r = fn(*a, **kw)
    except KeyError:
        raise HTTPException(404, '沒有這個工作')
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    if r is None:
        raise HTTPException(404, '沒有這個工作')
    return r


@router.get('/research_jobs/templates')
def api_templates():
    return RJ.templates()


@router.get('/research_jobs')
def api_state():
    return RJ.state()


@router.post('/research_jobs')
def api_create(body: dict = Body(...)):
    return _call(RJ.create, body.get('template'), body.get('params'), name=body.get('name'),
                 note=body.get('note'), hold=bool(body.get('hold')))


@router.post('/research_jobs/queue/{act}')
def api_queue(act: str):
    if act not in ('pause', 'resume'):
        raise HTTPException(400, '只有 pause／resume')
    r = RJ.set_paused(act == 'pause')
    RJ.tick()
    return r


@router.get('/research_jobs/{job_id}')
def api_get(job_id: int):
    return _call(RJ.get, job_id)


@router.patch('/research_jobs/{job_id}')
def api_update(job_id: int, body: dict = Body(...)):
    return _call(RJ.update, job_id, params=body.get('params'), name=body.get('name'), note=body.get('note'))


@router.delete('/research_jobs/{job_id}')
def api_delete(job_id: int):
    try:                                    # 刪完 get 會是 None，所以不走 _call
        RJ.action(job_id, 'delete')
    except KeyError:
        raise HTTPException(404, '沒有這個工作')
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return {'deleted': job_id}


@router.post('/research_jobs/{job_id}/{act}')
def api_action(job_id: int, act: str):
    if act not in ('cancel', 'hold', 'resume', 'up', 'down', 'top', 'clone'):
        raise HTTPException(400, '不認得的動作：%s' % act)
    return _call(RJ.action, job_id, act)


@router.get('/research_jobs/{job_id}/log')
def api_log(job_id: int, bytes: int = Query(20000, ge=1000, le=500000)):
    return _call(RJ.log, job_id, bytes)

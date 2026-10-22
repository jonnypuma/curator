import uuid
from fastapi import APIRouter
from pydantic import BaseModel

from curator.video import split
from resonance.errors import AppError

router = APIRouter()


def _valid_uuid(val: str, label: str = "Episode") -> str:
    try:
        return str(uuid.UUID(str(val)))
    except (ValueError, TypeError):
        raise AppError(f"{label} not found", 404)


class SplitBody(BaseModel):
    times: list[str] = []


class SplitJob(BaseModel):
    episode_id: str
    times: list[str] = []


class SplitBatchBody(BaseModel):
    jobs: list[SplitJob] = []


@router.post("/episodes/{episode_id}/split/plan")
def split_plan(episode_id: str):
    valid_id = _valid_uuid(episode_id)
    return split.plan(valid_id)


@router.post("/episodes/split/batch")
def split_batch(body: SplitBatchBody):
    jobs = []
    for job in body.jobs:
        jobs.append((_valid_uuid(job.episode_id), job.times))
    outcome = split.start_many(jobs)
    return {**outcome, "split": split.status()}


@router.post("/episodes/{episode_id}/split")
def split_run(episode_id: str, body: SplitBody):
    valid_id = _valid_uuid(episode_id)
    outcome = split.start(valid_id, body.times)
    return {**outcome, "split": split.status()}


@router.get("/episodes/split/status")
def split_status():
    return split.status()


@router.post("/episodes/{episode_id}/split/restore")
def split_restore(episode_id: str):
    valid_id = _valid_uuid(episode_id)
    return split.restore(valid_id)


@router.post("/episodes/{episode_id}/split/source")
def split_delete_source(episode_id: str):
    valid_id = _valid_uuid(episode_id)
    return split.delete_source(valid_id)

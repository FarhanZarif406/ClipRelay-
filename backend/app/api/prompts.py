from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select, update

from app.api.deps import DB, CurrentUser
from app.integrations import llm
from app.integrations.http import ApiError
from app.models import PromptTemplate, PromptTemplateVersion
from app.schemas import PromptIn, PromptOut, PromptTestIn, PromptTestOut
from app.services import activity, prompts

router = APIRouter(prefix="/prompts", tags=["prompts"])

SNAPSHOT_FIELDS = ["name", "description", "niche", "title_prompt", "caption_prompt", "hashtags_prompt", "is_enabled"]


def _get(db, prompt_id: int) -> PromptTemplate:
    template = db.get(PromptTemplate, prompt_id)
    if not template:
        raise HTTPException(404, "Prompt not found")
    return template


def _snapshot(db, template: PromptTemplate) -> None:
    version = (db.scalar(select(func.max(PromptTemplateVersion.version)).where(PromptTemplateVersion.template_id == template.id)) or 0) + 1
    db.add(PromptTemplateVersion(template_id=template.id, version=version, snapshot={f: getattr(template, f) for f in SNAPSHOT_FIELDS}))


@router.get("", response_model=list[PromptOut])
def list_prompts(db: DB, _: CurrentUser):
    return db.scalars(select(PromptTemplate).order_by(PromptTemplate.is_default.desc(), PromptTemplate.updated_at.desc())).all()


@router.get("/meta")
def meta(_: CurrentUser):
    cfg = llm.resolve()
    return {
        "variables": prompts.VARIABLES,
        "provider": cfg.provider if cfg else None,
        "model": cfg.model if cfg else None,
        "configured": bool(cfg and cfg.api_key),
    }


@router.post("", response_model=PromptOut, status_code=201)
def create_prompt(body: PromptIn, db: DB, _: CurrentUser):
    template = PromptTemplate(**body.model_dump())
    if not db.scalar(select(func.count(PromptTemplate.id))):
        template.is_default = True
    db.add(template)
    db.flush()
    _snapshot(db, template)
    activity.record(db, "AI rewrite", f"Prompt “{template.name}” created", event="prompt_created")
    db.commit()
    return template


@router.get("/{prompt_id}", response_model=PromptOut)
def get_prompt(prompt_id: int, db: DB, _: CurrentUser):
    return _get(db, prompt_id)


@router.put("/{prompt_id}", response_model=PromptOut)
def update_prompt(prompt_id: int, body: PromptIn, db: DB, _: CurrentUser):
    template = _get(db, prompt_id)
    for field, value in body.model_dump().items():
        setattr(template, field, value)
    db.flush()
    _snapshot(db, template)
    activity.record(db, "AI rewrite", f"Prompt “{template.name}” saved", event="prompt_saved")
    db.commit()
    return template


@router.delete("/{prompt_id}", status_code=204)
def delete_prompt(prompt_id: int, db: DB, _: CurrentUser):
    template = _get(db, prompt_id)
    if template.is_default:
        raise HTTPException(400, "Set another prompt as default before deleting this one")
    db.delete(template)
    db.commit()


@router.post("/{prompt_id}/default", response_model=PromptOut)
def make_default(prompt_id: int, db: DB, _: CurrentUser):
    template = _get(db, prompt_id)
    db.execute(update(PromptTemplate).values(is_default=False))
    template.is_default = True
    template.is_enabled = True
    db.commit()
    db.refresh(template)
    return template


@router.get("/{prompt_id}/versions")
def versions(prompt_id: int, db: DB, _: CurrentUser):
    _get(db, prompt_id)
    rows = db.scalars(
        select(PromptTemplateVersion).where(PromptTemplateVersion.template_id == prompt_id).order_by(PromptTemplateVersion.version.desc())
    ).all()
    return [{"version": r.version, "created_at": r.created_at, "snapshot": r.snapshot} for r in rows]


@router.post("/{prompt_id}/versions/{version}/restore", response_model=PromptOut)
def restore(prompt_id: int, version: int, db: DB, _: CurrentUser):
    template = _get(db, prompt_id)
    row = db.scalar(select(PromptTemplateVersion).where(PromptTemplateVersion.template_id == prompt_id, PromptTemplateVersion.version == version))
    if not row:
        raise HTTPException(404, "Version not found")
    for field in SNAPSHOT_FIELDS:
        if field in row.snapshot:
            setattr(template, field, row.snapshot[field])
    db.flush()
    _snapshot(db, template)
    db.commit()
    return template


@router.post("/test", response_model=PromptTestOut)
def test_prompt(body: PromptTestIn, db: DB, _: CurrentUser):
    try:
        result = prompts.rewrite(
            title_prompt=body.title_prompt,
            caption_prompt=body.caption_prompt,
            hashtags_prompt=body.hashtags_prompt,
            title=body.title or body.caption.split("\n", 1)[0][:120],
            caption=body.caption,
            tags=body.tags,
            niche=body.niche,
        )
    except ApiError as exc:
        raise HTTPException(502, f"LLM request failed: {exc}") from exc
    activity.record(db, "AI rewrite", "Prompt test run", event="prompt_tested")
    db.commit()
    return PromptTestOut(**result)

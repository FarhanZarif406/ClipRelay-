"""The main switch. Everyone can see whether the system is on; only the admin can switch it."""

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import DB, CurrentUser, OwnerUser
from app.services import system

router = APIRouter(tags=["system"])


class SwitchIn(BaseModel):
    on: bool


@router.get("/system")
def state(db: DB, user: CurrentUser):
    current = system.state(db)
    # Members see that it is off and when; who switched it is for the admins.
    return current if user.is_owner else {**current, "changed_by": None}


@router.put("/system")
def switch(body: SwitchIn, db: DB, user: OwnerUser):
    current = system.switch(db, body.on, user)
    db.commit()
    return current

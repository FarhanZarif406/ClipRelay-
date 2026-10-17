"""Whose keys apply right now: the owner's (shared by owners) or one member's own.

Each member uses their own AI models and their own YouTube Data API key, so the owner does not pay for everyone.
While the pipeline works on a member's video, or a member uses a feature, the code runs "acting for" that member,
and the AI model and the YouTube key are looked up for them only. `None` means the owners' own keys.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy.orm import Session

from app.models import User

_scope: ContextVar[int | None] = ContextVar("acting_for", default=None)


def scope_of(db: Session, user_id: int | None) -> int | None:
    """The key scope of an account: None for an owner (or no account), else the member's id."""
    if not user_id:
        return None
    user = db.get(User, user_id)
    return None if user is None or user.is_owner else user.id


def current() -> int | None:
    return _scope.get()


@contextmanager
def acting_for(db: Session, user_id: int | None) -> Iterator[None]:
    token = _scope.set(scope_of(db, user_id))
    try:
        yield
    finally:
        _scope.reset(token)


@contextmanager
def scope(value: int | None) -> Iterator[None]:
    """Act for a scope that is already known (None: the owners)."""
    token = _scope.set(value)
    try:
        yield
    finally:
        _scope.reset(token)

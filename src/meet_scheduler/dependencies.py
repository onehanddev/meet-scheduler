from collections.abc import Callable, Iterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from meet_scheduler.config import Settings
from meet_scheduler.hosts.models import Host
from meet_scheduler.security import get_host_id_from_access_token


def create_current_host_dependency(
    get_session: Callable[[], Iterator[Session]],
    get_settings: Callable[[], Settings],
):
    """Factory for the shared auth seam. Single place for host resolution.

    This is the **external seam** for authentication. All meeting-type and
    profile modules reuse this adapter, giving **locality**: auth changes
    concentrate here, not across N routers. **Depth** comes from hiding
    token parsing, host lookup, and error mapping behind one dependency.
    """

    def get_current_host(
        session: Annotated[Session, Depends(get_session)],
        authorization: Annotated[str | None, Header()] = None,
    ) -> Host:
        host_id = get_host_id_from_access_token(authorization, get_settings())
        host = session.get(Host, host_id)
        if host is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
            )
        return host

    return get_current_host

from __future__ import annotations

from typing import Any, Optional, cast
from urllib.parse import quote

from ._core import Request, drop_none
from .types import JsonDict, Project, ProjectList


def _seg(value: str) -> str:
    return quote(value, safe="")


class Projects:
    def __init__(self, client: Any) -> None:
        self._c = client

    def list(self) -> ProjectList:
        """List projects on the account and plan capacity."""
        return cast(ProjectList, self._c._send(Request("GET", "/v1/projects")))

    def create(self, name: str) -> JsonDict:
        """Create a new project on the account."""
        body = self._c._send(Request("POST", "/v1/projects", json={"name": name}))
        return cast(JsonDict, body["data"])

    def update(
        self,
        project_id: str,
        *,
        name: Optional[str] = None,
        strict_transforms: Optional[bool] = None,
    ) -> Project:
        """Rename a project or toggle ``strict_transforms``."""
        payload = drop_none({"name": name, "strict_transforms": strict_transforms})
        body = self._c._send(
            Request("PATCH", f"/v1/projects/{_seg(project_id)}", json=payload)
        )
        return cast(Project, body["data"])

    def delete(self, project_id: str) -> None:
        """Delete an empty project (an account must keep at least one project)."""
        self._c._send(Request("DELETE", f"/v1/projects/{_seg(project_id)}"))


class AsyncProjects:
    def __init__(self, client: Any) -> None:
        self._c = client

    async def list(self) -> ProjectList:
        return cast(ProjectList, await self._c._send(Request("GET", "/v1/projects")))

    async def create(self, name: str) -> JsonDict:
        body = await self._c._send(Request("POST", "/v1/projects", json={"name": name}))
        return cast(JsonDict, body["data"])

    async def update(
        self,
        project_id: str,
        *,
        name: Optional[str] = None,
        strict_transforms: Optional[bool] = None,
    ) -> Project:
        payload = drop_none({"name": name, "strict_transforms": strict_transforms})
        body = await self._c._send(
            Request("PATCH", f"/v1/projects/{_seg(project_id)}", json=payload)
        )
        return cast(Project, body["data"])

    async def delete(self, project_id: str) -> None:
        await self._c._send(Request("DELETE", f"/v1/projects/{_seg(project_id)}"))

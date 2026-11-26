from __future__ import annotations

import json

import httpx
import pytest

from pixelvault import AsyncPixelVault, PixelVault


def make(handler):
    return PixelVault(
        api_key="pv_live_test",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def amake(handler):
    return AsyncPixelVault(
        api_key="pv_live_test",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


PRESET = {
    "name": "avatar",
    "params": {"w": 256, "h": 256, "fit": "cover", "gravity": "face", "dpr": 2, "fmt": "auto"},
    "created_at": "2026-11-26T00:00:00Z",
    "updated_at": "2026-11-26T00:00:00Z",
}

PROJECT = {
    "id": "proj/1",
    "name": "Main",
    "strict_transforms": False,
    "created_at": "2026-11-26T00:00:00Z",
    "current": True,
}


def test_presets_list_upsert_delete():
    seen = []

    def handler(req):
        seen.append(req)
        if req.method == "GET":
            return httpx.Response(
                200,
                json={
                    "data": [PRESET],
                    "meta": {
                        "limit": 5,
                        "total": 1,
                        "strict_transforms": False,
                        "builtin_presets": ["s", "m", "l", "social", "square", "portrait"],
                    },
                },
            )
        if req.method == "PUT":
            return httpx.Response(201, json={"data": PRESET, "meta": {"limit": 5}})
        return httpx.Response(200, json={"data": {"deleted": True, "name": "avatar"}})

    pv = make(handler)
    listed = pv.presets.list()
    saved = pv.presets.upsert("avatar", PRESET["params"])
    pv.presets.delete("avatar")

    assert listed["meta"]["limit"] == 5
    assert listed["data"][0]["name"] == "avatar"
    assert saved["name"] == "avatar"
    assert seen[1].url.path == "/v1/presets/avatar"
    assert json.loads(seen[1].content) == {"params": PRESET["params"]}
    assert seen[2].method == "DELETE"


def test_projects_crud_and_strict_transforms():
    seen = []

    def handler(req):
        seen.append(req)
        if req.method == "GET":
            return httpx.Response(200, json={"data": [PROJECT], "meta": {"limit": 1, "total": 1}})
        if req.method == "POST":
            return httpx.Response(201, json={"data": {**PROJECT, "id": "proj_2", "name": "Staging"}})
        if req.method == "PATCH":
            return httpx.Response(200, json={"data": {**PROJECT, "strict_transforms": True}})
        return httpx.Response(200, json={"data": {"deleted": True, "id": "proj/1"}})

    pv = make(handler)
    listed = pv.projects.list()
    created = pv.projects.create("Staging")
    updated = pv.projects.update("proj/1", strict_transforms=True)
    pv.projects.delete("proj/1")

    assert listed["meta"]["limit"] == 1
    assert created["id"] == "proj_2"
    assert updated["strict_transforms"] is True
    assert seen[2].url.raw_path == b"/v1/projects/proj%2F1"
    assert json.loads(seen[2].content) == {"strict_transforms": True}
    assert seen[3].method == "DELETE"


def test_sign_url_with_transforms():
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(
            200,
            json={
                "data": {
                    "url": "https://img.pixelvault.dev/p/cp/i/img_1.png?token=sig&expires=1900000000&w=800&fmt=auto",
                    "expires": 1900000000,
                    "expires_at": "2026-11-26T12:00:00Z",
                }
            },
        )

    pv = make(handler)
    signed = pv.images.sign_url(
        "img_1",
        1800,
        transforms={"w": 800, "fmt": "auto", "watermark": "img_logo.png"},
    )
    assert "w=800" in signed["url"]
    assert json.loads(seen[0].content) == {
        "expires_in": 1800,
        "transforms": {"w": 800, "fmt": "auto", "watermark": "img_logo.png"},
    }


@pytest.mark.asyncio
async def test_async_presets_projects_and_sign_url():
    seen = []

    def handler(req):
        seen.append(req)
        if req.url.path == "/v1/presets":
            return httpx.Response(
                200,
                json={
                    "data": [PRESET],
                    "meta": {"limit": 5, "total": 1, "strict_transforms": True, "builtin_presets": ["s"]},
                },
            )
        if req.url.path == "/v1/presets/avatar" and req.method == "PUT":
            return httpx.Response(200, json={"data": PRESET})
        if req.url.path == "/v1/presets/avatar" and req.method == "DELETE":
            return httpx.Response(200, json={"data": {"deleted": True, "name": "avatar"}})
        if req.url.path == "/v1/projects/proj_1" and req.method == "PATCH":
            return httpx.Response(200, json={"data": {**PROJECT, "id": "proj_1", "strict_transforms": True}})
        return httpx.Response(
            200,
            json={"data": {"url": "https://img.pixelvault.dev/p/cp/i/img_1.png?token=sig&expires=1900000000", "expires": 1900000000}},
        )

    async with amake(handler) as pv:
        listed = await pv.presets.list()
        saved = await pv.presets.upsert("avatar", {"w": 256})
        await pv.presets.delete("avatar")
        updated = await pv.projects.update("proj_1", strict_transforms=True)
        signed = await pv.images.sign_url("img_1", transforms={"size": "avatar", "dpr": 2})

    assert listed["meta"]["strict_transforms"] is True
    assert saved["name"] == "avatar"
    assert updated["strict_transforms"] is True
    assert signed["expires"] == 1900000000
    assert json.loads(seen[-1].content) == {"transforms": {"size": "avatar", "dpr": 2}}

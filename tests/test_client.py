import json
from pathlib import Path

import httpx
import pytest

from pixelvault import AsyncPixelVault, PixelVault, PixelVaultError, __version__

IMG = {"id": "img_1", "url": "https://img.pixelvault.dev/p/i.png", "filename": "a.png"}


def make(handler, **kw):
    kw.setdefault("api_key", "pv_live_test")
    return PixelVault(http_client=httpx.Client(transport=httpx.MockTransport(handler)), **kw)


def amake(handler, **kw):
    kw.setdefault("api_key", "pv_live_test")
    return AsyncPixelVault(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), **kw
    )


def test_version_matches_pyproject():
    text = (Path(__file__).parent.parent / "pyproject.toml").read_text()
    assert f'version = "{__version__}"' in text


def test_upload_bytes_sends_multipart_with_headers():
    seen = {}

    def handler(req: httpx.Request):
        seen["req"] = req
        return httpx.Response(201, json={"data": IMG})

    img = make(handler).images.upload(b"\x89PNG", filename="a.png", expires_in=3600, visibility="private")
    assert img["id"] == "img_1"
    req = seen["req"]
    assert str(req.url) == "https://api.pixelvault.dev/v1/images"
    assert req.headers["authorization"] == "Bearer pv_live_test"
    assert req.headers["x-pixelvault-client"] == f"sdk-python/{__version__}"
    assert req.headers["content-type"].startswith("multipart/form-data")
    body = req.content
    assert b'name="expires_in"' in body and b"3600" in body
    assert b'filename="a.png"' in body and b"image/png" in body


def test_upload_path(tmp_path):
    f = tmp_path / "shot.png"
    f.write_bytes(b"png")
    seen = {}

    def handler(req):
        seen["body"] = req.content
        return httpx.Response(201, json={"data": IMG})

    make(handler).images.upload(f)
    assert b'filename="shot.png"' in seen["body"]


def test_upload_url_is_json_snake_case():
    seen = {}

    def handler(req):
        seen["json"] = json.loads(req.content)
        return httpx.Response(201, json={"data": IMG})

    make(handler).images.upload(url="https://example.com/x.png", expires_in=60, sign_expires_in=120)
    assert seen["json"] == {"url": "https://example.com/x.png", "expires_in": 60, "sign_expires_in": 120}


def test_upload_requires_exactly_one_source():
    c = make(lambda r: httpx.Response(200, json={}))
    with pytest.raises(ValueError):
        c.images.upload()
    with pytest.raises(ValueError):
        c.images.upload(b"x", url="https://example.com/x.png")


def test_no_key_means_no_authorization_header(monkeypatch):
    monkeypatch.delenv("PIXELVAULT_API_KEY", raising=False)
    seen = {}

    def handler(req):
        seen["auth"] = req.headers.get("authorization")
        return httpx.Response(201, json={"data": IMG})

    PixelVault(http_client=httpx.Client(transport=httpx.MockTransport(handler))).images.upload(b"x")
    assert seen["auth"] is None


def test_env_key_fallback(monkeypatch):
    monkeypatch.setenv("PIXELVAULT_API_KEY", "pv_live_env")
    seen = {}

    def handler(req):
        seen["auth"] = req.headers.get("authorization")
        return httpx.Response(200, json={"data": {"plan": "free"}})

    PixelVault(http_client=httpx.Client(transport=httpx.MockTransport(handler))).usage.get()
    assert seen["auth"] == "Bearer pv_live_env"


def test_error_mapping_and_long_retry_after_fails_fast():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(
            429,
            json={"error": {"code": "upload_limit_reached", "message": "Upgrade"}},
            headers={"Retry-After": "3600"},
        )

    with pytest.raises(PixelVaultError) as e:
        make(handler).usage.get()
    assert (e.value.status, e.value.code, e.value.retry_after) == (429, "upload_limit_reached", 3600.0)
    assert len(calls) == 1


def test_retries_429_with_short_retry_after():
    responses = [
        httpx.Response(429, json={"error": {"code": "rate_limited", "message": "slow"}}, headers={"Retry-After": "0"}),
        httpx.Response(200, json={"data": {"plan": "free"}}),
    ]
    assert make(lambda r: responses.pop(0)).usage.get()["plan"] == "free"


def test_does_not_retry_5xx_on_upload():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(500, json={"error": {"code": "internal", "message": "boom"}})

    with pytest.raises(PixelVaultError) as e:
        make(handler).images.upload(b"x")
    assert e.value.status == 500 and len(calls) == 1


def test_retries_get_on_5xx(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    responses = [httpx.Response(503, json={}), httpx.Response(200, json={"data": IMG})]
    assert make(lambda r: responses.pop(0)).images.get("img_1")["id"] == "img_1"


def test_network_error_wrapped():
    def handler(req):
        raise httpx.ConnectError("down")

    with pytest.raises(PixelVaultError) as e:
        make(handler, max_retries=0).images.delete("img_1")
    assert (e.value.status, e.value.code) == (0, "network_error")


def test_list_all_walks_pages():
    pages = {
        "1": {"data": [{"id": "a"}, {"id": "b"}], "meta": {"total": 3, "page": 1, "per_page": 2}},
        "2": {"data": [{"id": "c"}], "meta": {"total": 3, "page": 2, "per_page": 2}},
    }

    def handler(req):
        return httpx.Response(200, json=pages[req.url.params["page"]])

    assert [i["id"] for i in make(handler).images.list_all(per_page=2)] == ["a", "b", "c"]


def test_keys_create_and_revoke_encode_ids():
    seen = []

    def handler(req):
        seen.append((req.method, req.url.raw_path.decode(), req.content))
        return httpx.Response(201, json={"data": {"id": "key_1", "api_key": "pv_live_new"}})

    c = make(handler)
    assert c.keys.create(label="ci", environment="test")["api_key"] == "pv_live_new"
    c.keys.revoke("key/1")
    assert json.loads(seen[0][2]) == {"label": "ci", "environment": "test"}
    assert seen[1][:2] == ("DELETE", "/v1/keys/key%2F1")


def test_device_login_sends_no_auth():
    seen = {}

    def handler(req):
        seen["auth"] = req.headers.get("authorization")
        seen["json"] = json.loads(req.content)
        return httpx.Response(200, json={"data": {"api_key": "pv_live_x"}})

    make(handler).device_login_complete("a@b.co", "123456", replace_existing=True)
    assert seen["auth"] is None and seen["json"]["replace_existing"] is True


async def test_async_upload_and_list_all():
    def handler(req):
        if req.method == "POST":
            return httpx.Response(201, json={"data": IMG})
        return httpx.Response(200, json={"data": [{"id": "a"}], "meta": {"total": 1, "page": 1, "per_page": 1}})

    async with amake(handler) as pv:
        assert (await pv.images.upload(b"x"))["id"] == "img_1"
        assert [i["id"] async for i in pv.images.list_all()] == ["a"]


async def test_async_error():
    async with amake(lambda r: httpx.Response(401, json={"error": {"code": "missing_api_key", "message": "no key"}})) as pv:
        with pytest.raises(PixelVaultError) as e:
            await pv.usage.get()
    assert e.value.code == "missing_api_key"


GENERATED = {
    **IMG,
    "optimized_url": "https://img.pixelvault.dev/p/i.png?fmt=auto&q=85",
    "generation": {"model": "flux-1-schnell", "credits_charged": 1, "credits_remaining": 9},
}


def test_generate_posts_json_and_returns_generation():
    seen = {}

    def handler(req: httpx.Request):
        seen["req"] = req
        return httpx.Response(201, json={"data": GENERATED})

    img = make(handler).images.generate(
        "a red bicycle", model="lucid-origin", folder="heroes", expires_in=3600
    )
    req = seen["req"]
    assert req.method == "POST"
    assert str(req.url) == "https://api.pixelvault.dev/v1/images/generate"
    assert req.headers["authorization"] == "Bearer pv_live_test"
    assert req.headers["content-type"].startswith("application/json")
    assert json.loads(req.content) == {
        "prompt": "a red bicycle",
        "model": "lucid-origin",
        "folder": "heroes",
        "expires_in": 3600,
    }
    assert img["generation"]["credits_remaining"] == 9
    assert img["optimized_url"].endswith("fmt=auto&q=85")


def test_generate_omits_unset_options():
    seen = {}

    def handler(req: httpx.Request):
        seen["body"] = json.loads(req.content)
        return httpx.Response(201, json={"data": GENERATED})

    make(handler).images.generate("a lake")
    assert seen["body"] == {"prompt": "a lake"}


def test_generate_credit_errors_carry_the_api_code():
    def handler(req: httpx.Request):
        return httpx.Response(
            402,
            json={"error": {"code": "generation_credits_exhausted", "message": "0 left"}},
        )

    with pytest.raises(PixelVaultError) as exc:
        make(handler).images.generate("x")
    assert exc.value.status == 402
    assert exc.value.code == "generation_credits_exhausted"


def test_generate_is_not_retried_after_a_5xx():
    calls = []

    def handler(req: httpx.Request):
        calls.append(1)
        return httpx.Response(
            502, json={"error": {"code": "generation_failed", "message": "try again"}}
        )

    with pytest.raises(PixelVaultError) as exc:
        make(handler).images.generate("x")
    assert exc.value.code == "generation_failed"
    assert len(calls) == 1  # a lost response must never spend credits twice


def test_usage_exposes_generation_credits():
    usage = {
        "plan": "free",
        "generation": {"credits_used": 1, "credits_limit": 10, "credits_remaining": 9},
    }
    got = make(lambda r: httpx.Response(200, json={"data": usage})).usage.get()
    assert got["generation"]["credits_remaining"] == 9


@pytest.mark.asyncio
async def test_async_generate():
    seen = {}

    def handler(req: httpx.Request):
        seen["body"] = json.loads(req.content)
        return httpx.Response(201, json={"data": GENERATED})

    async with amake(handler) as pv:
        img = await pv.images.generate("a mountain", visibility="private")
    assert seen["body"] == {"prompt": "a mountain", "visibility": "private"}
    assert img["generation"]["model"] == "flux-1-schnell"


def test_upload_metadata_multipart_and_json():
    seen = []

    def handler(req: httpx.Request):
        seen.append(req)
        return httpx.Response(201, json={"data": IMG})

    pv = make(handler)
    pv.images.upload(b"\x89PNG", filename="a.png", metadata={"env": "prod", "n": 3})
    body = seen[0].read().decode("latin-1")
    assert 'name="metadata"' in body and '{"env": "prod", "n": 3}' in body

    pv.images.upload(url="https://example.com/a.png", metadata={"a": 1})
    assert json.loads(seen[1].content)["metadata"] == {"a": 1}

    pv.images.upload(url="https://example.com/a.png", metadata={})
    assert "metadata" not in json.loads(seen[2].content)


def test_list_metadata_filter_param_and_list_all():
    seen = []

    def handler(req: httpx.Request):
        seen.append(req)
        return httpx.Response(200, json={"data": [], "meta": {"total": 0, "page": 1, "per_page": 20}})

    pv = make(handler)
    pv.images.list(metadata={"env": "prod"})
    assert json.loads(seen[0].url.params["metadata"]) == {"env": "prod"}
    pv.images.list(metadata={})
    assert "metadata" not in seen[1].url.params
    list(pv.images.list_all(metadata={"a": 1}))
    assert json.loads(seen[2].url.params["metadata"]) == {"a": 1}


def test_update_metadata_patches_and_clears():
    seen = []

    def handler(req: httpx.Request):
        seen.append(req)
        return httpx.Response(200, json={"data": {"id": "img_1", "metadata": json.loads(req.content)["metadata"]}})

    pv = make(handler)
    assert pv.images.update_metadata("img_1", {"a": 1}) == {"a": 1}
    assert seen[0].method == "PATCH" and seen[0].url.path == "/v1/images/img_1"
    assert pv.images.update_metadata("img_1", None) is None
    assert json.loads(seen[1].content) == {"metadata": None}


@pytest.mark.asyncio
async def test_async_metadata_roundtrip():
    seen = []

    def handler(req: httpx.Request):
        seen.append(req)
        if req.method == "PATCH":
            return httpx.Response(200, json={"data": {"id": "img_1", "metadata": {"a": 1}}})
        return httpx.Response(200, json={"data": [], "meta": {"total": 0, "page": 1, "per_page": 20}})

    pv = amake(handler)
    await pv.images.list(metadata={"env": "prod"})
    assert json.loads(seen[0].url.params["metadata"]) == {"env": "prod"}
    assert await pv.images.update_metadata("img_1", {"a": 1}) == {"a": 1}


def test_describe_flag_multipart_and_json():
    seen = []

    def handler(req: httpx.Request):
        seen.append(req)
        return httpx.Response(201, json={"data": IMG})

    pv = make(handler)
    pv.images.upload(b"\x89PNG", filename="a.png", describe=True)
    assert 'name="describe"' in seen[0].read().decode("latin-1")
    pv.images.upload(b"\x89PNG", filename="a.png")
    assert 'name="describe"' not in seen[1].read().decode("latin-1")
    pv.images.upload(url="https://example.com/a.png", describe=True)
    assert json.loads(seen[2].content)["describe"] is True
    pv.images.upload(url="https://example.com/a.png")
    assert "describe" not in json.loads(seen[3].content)


def test_list_q_param():
    seen = []

    def handler(req: httpx.Request):
        seen.append(req)
        return httpx.Response(200, json={"data": [], "meta": {"total": 0, "page": 1, "per_page": 20}})

    pv = make(handler)
    pv.images.list(q="invoice 4821")
    assert seen[0].url.params["q"] == "invoice 4821"
    pv.images.list(q="  ")
    assert "q" not in seen[1].url.params
    list(pv.images.list_all(q="cat"))
    assert seen[2].url.params["q"] == "cat"


def test_wait_for_description_polls_until_done_and_gives_up():
    states = [{"status": "pending"}, {"status": "pending"}, {"status": "done", "alt": "A cat"}]
    calls = []

    def handler(req: httpx.Request):
        calls.append(req)
        i = min(len(calls) - 1, len(states) - 1)
        return httpx.Response(200, json={"data": {**IMG, "description": states[i]}})

    pv = make(handler)
    assert pv.images.wait_for_description("img_1", interval=0.001)["alt"] == "A cat"
    assert len(calls) == 3

    pv2 = make(lambda req: httpx.Response(200, json={"data": {**IMG, "description": {"status": "failed", "error": "describe_timeout"}}}))
    assert pv2.images.wait_for_description("img_1", interval=0.001)["status"] == "failed"
    pv3 = make(lambda req: httpx.Response(200, json={"data": {**IMG, "description": None}}))
    assert pv3.images.wait_for_description("img_1", interval=0.001) is None
    pv4 = make(lambda req: httpx.Response(200, json={"data": {**IMG, "description": {"status": "pending"}}}))
    assert pv4.images.wait_for_description("img_1", timeout=0.01, interval=0.001)["status"] == "pending"


@pytest.mark.asyncio
async def test_async_describe_roundtrip():
    states = [{"status": "pending"}, {"status": "done", "alt": "x"}]
    calls = []

    def handler(req: httpx.Request):
        calls.append(req)
        if req.method == "GET" and req.url.path.startswith("/v1/images/"):
            return httpx.Response(200, json={"data": {**IMG, "description": states[min(len(calls) - 1, 1)]}})
        return httpx.Response(200, json={"data": [], "meta": {"total": 0, "page": 1, "per_page": 20}})

    pv = amake(handler)
    await pv.images.list(q="invoice")
    assert calls[0].url.params["q"] == "invoice"
    assert (await pv.images.wait_for_description("img_1", interval=0.001))["alt"] == "x"


VIDEO = {
    "id": "vid_1",
    "kind": "video",
    "url": "https://img.pixelvault.dev/p/vid_1.mp4",
    "original_url": "https://img.pixelvault.dev/p/vid_1.mp4",
    "visibility": "public",
    "mime_type": "video/mp4",
    "size": 3,
    "width": 1920,
    "height": 1080,
    "duration_seconds": 2.0,
    "video_codec": "h264",
    "audio_codec": "aac",
    "has_audio": True,
    "fast_start": True,
    "social_compatible": True,
    "compatibility_warnings": [],
    "social_optimization": {"status": "not_requested"},
    "enrichment": {"status": "not_requested"},
    "filename": "clip.mp4",
    "folder": None,
    "collection_id": None,
    "metadata": None,
    "created_at": "2026-11-16T00:00:00Z",
}


def test_video_upload_bytes_sends_lifecycle_and_idempotency_headers():
    seen = {}

    def handler(req):
        seen["request"] = req
        return httpx.Response(201, json={"data": VIDEO})

    video = make(handler).videos.upload(
        b"mp4",
        filename="hello world.mp4",
        visibility="private",
        sign_expires_in=300,
        expires_in=3600,
        folder="demos",
        collection_id="col_1",
        metadata={"env": "test"},
        social_ready=True,
        idempotency_key="retry-1",
        sha256="abc123",
    )
    req = seen["request"]
    assert video["id"] == "vid_1"
    assert req.content == b"mp4"
    assert req.headers["x-pixelvault-filename"] == "hello%20world.mp4"
    assert req.headers["x-pixelvault-visibility"] == "private"
    assert req.headers["x-pixelvault-sign-expires-in"] == "300"
    assert req.headers["x-pixelvault-expires-in"] == "3600"
    assert req.headers["x-pixelvault-folder"] == "demos"
    assert req.headers["x-pixelvault-collection-id"] == "col_1"
    assert json.loads(req.headers["x-pixelvault-metadata"]) == {"env": "test"}
    assert req.headers["idempotency-key"] == "retry-1"
    assert req.headers["x-pixelvault-content-sha256"] == "abc123"


def test_video_import_is_json_and_replay_safe():
    seen = {}

    def handler(req):
        seen["request"] = req
        return httpx.Response(201, json={"data": VIDEO})

    make(handler).videos.upload(
        url="https://example.com/clip.mp4",
        filename="clip.mp4",
        metadata={"source": "demo"},
        idempotency_key="import-1",
    )
    req = seen["request"]
    assert req.headers["idempotency-key"] == "import-1"
    assert json.loads(req.content) == {
        "url": "https://example.com/clip.mp4",
        "filename": "clip.mp4",
        "metadata": {"source": "demo"},
    }


def test_video_resumable_upload_and_abort():
    seen = []

    def handler(req):
        seen.append(req)
        path = req.url.path
        if path == "/v1/videos/uploads":
            return httpx.Response(
                201,
                json={
                    "data": {
                        "upload_id": "vup_1",
                        "asset_id": "vid_1",
                        "part_size": 2,
                        "size": 3,
                        "visibility": "private",
                        "expires_at": "2026-11-16T01:00:00Z",
                    }
                },
            )
        if "/parts/" in path:
            number = int(path.rsplit("/", 1)[1])
            return httpx.Response(
                200,
                json={"data": {"part_number": number, "etag": str(number), "received": len(req.content)}},
            )
        if path.endswith("/complete"):
            return httpx.Response(201, json={"data": VIDEO})
        if req.method == "DELETE":
            return httpx.Response(204)
        raise AssertionError(path)

    pv = make(handler)
    video = pv.videos.upload_resumable(
        b"abc", filename="clip.mp4", visibility="private", idempotency_key="resume-1"
    )
    pv.videos.abort_upload("vup_old")
    assert video["id"] == "vid_1"
    assert [request.method for request in seen] == ["POST", "PUT", "PUT", "POST", "DELETE"]
    assert seen[0].headers["idempotency-key"] == "resume-1"
    assert json.loads(seen[0].content)["sha256"] == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert seen[1].headers["x-pixelvault-part-sha256"]
    assert seen[2].content == b"c"


def test_video_lifecycle_jobs_filters_and_wait_states():
    seen = []
    states = [
        {**VIDEO, "enrichment": {"status": "complete", "job_id": "ven_1"}},
        {**VIDEO, "social_optimization": {"status": "processing", "job_id": "vop_1"}},
    ]

    def handler(req):
        seen.append(req)
        if req.method == "DELETE":
            return httpx.Response(204)
        if req.url.path == "/v1/videos" and req.method == "GET":
            return httpx.Response(
                200, json={"data": [VIDEO], "meta": {"total": 1, "page": 1, "per_page": 20}}
            )
        if req.url.path.endswith("/sign-url"):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "url": "https://signed.example/video.mp4?sig=x",
                        "enrichment": VIDEO["enrichment"],
                        "expires": 123,
                    }
                },
            )
        if req.method == "GET":
            return httpx.Response(200, json={"data": states.pop(0)})
        return httpx.Response(200, json={"data": VIDEO})

    pv = make(handler)
    page = pv.videos.list(folder="demos", collection_id="col_1", metadata={"env": "test"})
    pv.videos.update("vid_1", metadata=None, folder="archive", collection_id=None)
    signed = pv.videos.sign_url("vid_1", 300)
    pv.videos.optimize("vid_1")
    pv.videos.enrich("vid_1")
    pv.videos.analyze("vid_1")
    pv.videos.create_poster("vid_1")
    pv.videos.delete("vid_1")
    complete = pv.videos.wait_for_enrichment("vid_1", timeout=0)
    timed_out = pv.videos.wait_for_optimization("vid_1", timeout=0)
    assert page["meta"]["total"] == 1
    assert json.loads(seen[0].url.params["metadata"]) == {"env": "test"}
    assert json.loads(seen[1].content) == {
        "metadata": None,
        "folder": "archive",
        "collection_id": None,
    }
    assert signed["url"] == "https://signed.example/video.mp4?sig=x"
    assert complete["status"] == "complete" and complete["timed_out"] is False
    assert timed_out["status"] == "processing" and timed_out["timed_out"] is True


@pytest.mark.asyncio
async def test_async_video_import_resumable_and_wait():
    calls = []
    states = [{**VIDEO, "enrichment": {"status": "failed", "job_id": "ven_1"}}]

    def handler(req):
        calls.append(req)
        if req.url.path == "/v1/videos" and req.method == "POST":
            return httpx.Response(201, json={"data": VIDEO})
        if req.url.path == "/v1/videos/uploads":
            return httpx.Response(
                201,
                json={
                    "data": {
                        "upload_id": "vup_1",
                        "asset_id": "vid_1",
                        "part_size": 8,
                        "size": 3,
                        "visibility": "public",
                        "expires_at": "2026-11-16T01:00:00Z",
                    }
                },
            )
        if "/parts/" in req.url.path:
            return httpx.Response(
                200, json={"data": {"part_number": 1, "etag": "a", "received": 3}}
            )
        if req.url.path.endswith("/complete"):
            return httpx.Response(201, json={"data": VIDEO})
        if req.method == "GET":
            return httpx.Response(200, json={"data": states.pop(0)})
        raise AssertionError(req.url.path)

    async with amake(handler) as pv:
        imported = await pv.videos.upload(url="https://example.com/clip.mp4")
        resumed = await pv.videos.upload_resumable(
            b"abc", filename="clip.mp4", idempotency_key="async-1"
        )
        result = await pv.videos.wait_for_enrichment("vid_1", timeout=0)
    assert imported["id"] == resumed["id"] == "vid_1"
    assert result["status"] == "failed" and result["timed_out"] is False


def test_exports_start_wait_and_download_bytes():
    seen = []

    def handler(req):
        seen.append(req)
        if req.url.path == "/v1/export":
            return httpx.Response(
                202,
                json={
                    "job_id": "exp_1",
                    "status": "pending",
                    "image_count": 2,
                    "video_count": 1,
                    "asset_count": 3,
                    "status_url": "/v1/export-jobs/exp_1",
                },
            )
        if req.url.path.endswith("/download"):
            return httpx.Response(200, content=b"tar!", headers={"content-type": "application/x-tar"})
        return httpx.Response(
            200,
            json={
                "id": "exp_1",
                "status": "complete",
                "image_count": 2,
                "video_count": 1,
                "asset_count": 3,
                "processed_count": 3,
                "bytes": 4,
                "created_at": "2026-11-16T00:00:00Z",
                "expires_at": "2026-11-17T00:00:00Z",
                "download_url": "/v1/export-jobs/exp_1/download",
            },
        )

    pv = make(handler)
    started = pv.exports.start(project_id="proj_1")
    waited = pv.exports.wait(started["job_id"], project_id="proj_1", timeout=0)
    archive = pv.exports.download(started["job_id"], project_id="proj_1")
    assert started["video_count"] == 1
    assert waited["job"]["status"] == "complete" and waited["timed_out"] is False
    assert archive == b"tar!"
    assert all(req.url.params["project_id"] == "proj_1" for req in seen)
    assert seen[2].headers["accept"] == "application/x-tar"


@pytest.mark.asyncio
async def test_async_exports_timeout_is_local():
    def handler(req):
        if req.url.path == "/v1/export":
            return httpx.Response(
                202,
                json={
                    "job_id": "exp_1",
                    "status": "pending",
                    "image_count": 0,
                    "video_count": 1,
                    "asset_count": 1,
                    "status_url": "/v1/export-jobs/exp_1",
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "exp_1",
                "status": "processing",
                "image_count": 0,
                "video_count": 1,
                "asset_count": 1,
                "processed_count": 0,
                "bytes": 0,
                "created_at": "2026-11-16T00:00:00Z",
                "expires_at": "2026-11-17T00:00:00Z",
            },
        )

    async with amake(handler) as pv:
        started = await pv.exports.start()
        result = await pv.exports.wait(started["job_id"], timeout=0)
    assert result["job"]["status"] == "processing" and result["timed_out"] is True

# pixelvault

Official Python SDK for [PixelVault](https://pixelvault.dev), agent-first image hosting.
Sync and asyncio clients on top of `httpx`. Python 3.9+.

```bash
pip install pixelvault
```

## Quick start

```python
from pixelvault import PixelVault

pv = PixelVault()  # reads PIXELVAULT_API_KEY, or pass api_key="pv_live_..."

# A path, bytes or a binary file object
image = pv.images.upload("screenshot.png")
print(image["url"])  # https://img.pixelvault.dev/...

# Import from a URL, auto-delete after one hour
pv.images.upload(url="https://example.com/a.png", expires_in=3600)
```

With no API key at all, `images.upload(file)` makes an anonymous upload that expires after 30 days.

Generate an image from a prompt and host it in one call (spends monthly credits, see the table below):

```python
image = pv.images.generate("flat vector hero, a robot at a laptop, no text")
print(image["url"])         # https://img.pixelvault.dev/...
print(image["generation"])  # {'model': 'flux-1-schnell', 'credits_charged': 1, 'credits_remaining': 9}
```

Asyncio:

```python
from pixelvault import AsyncPixelVault

async with AsyncPixelVault() as pv:
    image = await pv.images.upload("screenshot.png")
    async for img in pv.images.list_all():
        print(img["id"])
```

## API

| Call | What it does |
|---|---|
| `images.upload(file \| url=, folder=, visibility=, expires_in=, sign_expires_in=)` | Upload a file or import a URL |
| `images.generate(prompt, model=, folder=, visibility=, expires_in=)` | Generate an image from a prompt and host it. Credits: `flux-1-schnell` and the SDXL models 1, Leonardo 20. Free plan: 10 credits a month, `flux-1-schnell` only |
| `images.upload_batch(collection, images)` | Up to 50 images in one collection |
| `images.list(page=, per_page=)` / `images.list_all()` | One page / iterator over all images |
| `images.get(id)` / `images.delete(id)` | Fetch / delete one image |
| `images.sign_url(id, expires_in=)` | Signed URL for a private image |
| `usage.get()` | Plan, usage, limits and what is left this month (including generation credits) |
| `keys.list()` / `keys.create(label=, environment=)` / `keys.revoke(id)` | Manage your API keys (secret keys only) |
| `register(email)` | Create an account, returns a first key once |
| `device_login_start(email)` + `device_login_complete(email, code)` | Passwordless key minting |

## Errors and retries

Every failure raises `PixelVaultError` with `.status` (0 for network errors), `.code` (for example
`upload_limit_reached`) and `.retry_after` (seconds, when sent).

```python
from pixelvault import PixelVault, PixelVaultError

try:
    pv.images.upload("big.png")
except PixelVaultError as err:
    if err.code == "upload_limit_reached":
        print(err.message)  # links to the pricing page
```

The client retries `429` (honoring `Retry-After` up to 30 seconds) and, for `GET`/`DELETE` only, `5xx` and
network errors. Uploads and `images.generate` are never retried after a `5xx` or a network error, so a lost response cannot create a duplicate image or spend credits twice.
Tune with `max_retries` (default 2) and `timeout` (seconds, default 60).

## License

MIT

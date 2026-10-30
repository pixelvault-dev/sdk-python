"""Fail when the live API gains an operation this SDK neither wraps nor ignores.

Run in CI on every push and weekly, so an API change turns this repo red
until someone decides whether the SDK should cover it.
"""

import json
import sys
import urllib.request

COVERED = {
    "upload_image", "generate_image", "batch_upload", "list_images", "get_image", "delete_image",
    "sign_image_url", "get_usage", "list_keys", "create_key", "revoke_key",
    "register_account", "device_login_start", "device_login_complete",
}
# Not wrapped on purpose: dashboard-session endpoints, the public playground,
# health, and surfaces the SDK does not cover yet.
IGNORED = {
    "claim_upload", "dashboard_upload", "dashboard_delete_image", "playground_upload",
    "health_check", "serve_image",
    # Billing: a person pays or cancels, so it is a dashboard/portal flow, not an SDK call.
    "start_checkout", "open_billing_portal",
    "list_collections", "get_collection", "close_collection",
    "start_export", "get_export_job", "download_export",
}

req = urllib.request.Request(
    "https://api.pixelvault.dev/openapi.json",
    headers={"User-Agent": "pixelvault-sdk-python-ci"},
)
with urllib.request.urlopen(req) as res:
    spec = json.load(res)

live = {
    op["operationId"]
    for item in spec["paths"].values()
    for op in item.values()
    if isinstance(op, dict) and "operationId" in op
}
new = sorted(live - COVERED - IGNORED)
gone = sorted(COVERED - live)
if new or gone:
    print(f"New operations to cover or ignore: {new}")
    print(f"Covered operations no longer in the API: {gone}")
    sys.exit(1)
print(f"spec coverage ok: {len(COVERED)} covered, {len(IGNORED)} ignored")

#!/usr/bin/env python3
"""Pull the workflow from n8n and write a shareable, sanitized copy.

The n8n public API already redacts credential secrets and any value stored in a
credential, but a raw export still carries instance-specific state: the workflow
id, version counters, the Google Sheet it writes to, and the credential ids from
one particular n8n account. This strips all of that so the JSON imports cleanly
into any instance.

Usage:
    export N8N_BASE_URL=https://your-instance.app.n8n.cloud
    export N8N_API_KEY=...
    python3 scripts/export_workflow.py --id 7tPzUPeBYj5DO5As

    # or sanitize a file you exported from the n8n UI
    python3 scripts/export_workflow.py --file raw-export.json
"""

import argparse
import json
import os
import re
import sys
import urllib.request

OUTPUT = "workflow/facebook-ads-spy-agent.json"

SHEET_PLACEHOLDER = "YOUR_GOOGLE_SHEET_ID"
CRED_PLACEHOLDER = "REPLACE_WITH_YOUR_CREDENTIAL_ID"

# Credential type -> the generic name shown after import.
CRED_NAMES = {
    "googleDriveOAuth2Api": "Google Drive account",
    "googleSheetsOAuth2Api": "Google Sheets account",
    "openAiApi": "OpenAI account",
}

# Instance-specific keys that must not travel with a shared workflow.
DROP_KEYS = {
    "id", "versionId", "activeVersionId", "versionCounter", "sourceWorkflowId",
    "shared", "activeVersion", "triggerCount", "createdAt", "updatedAt",
    "isArchived", "tags", "active", "meta", "description", "staticData",
}

# Anything shaped like a live key. The API should never return these, so a hit
# means the export came from somewhere else and needs a human look.
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"apify_api_[A-Za-z0-9]{20,}"),
    re.compile(r"AIza[A-Za-z0-9_-]{30,}"),
    re.compile(r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\."),
]


def fetch(base_url, api_key, workflow_id):
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/v1/workflows/{workflow_id}",
        headers={"X-N8N-API-KEY": api_key, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def sanitize(wf):
    clean = {k: v for k, v in wf.items() if k not in DROP_KEYS}
    clean.setdefault("name", "Facebook Ads Spy Agent")
    clean.setdefault("settings", {"executionOrder": "v1", "binaryMode": "separate"})
    clean["pinData"] = {}

    for node in clean.get("nodes", []):
        for cred_type, cred in node.get("credentials", {}).items():
            cred["id"] = CRED_PLACEHOLDER
            cred["name"] = CRED_NAMES.get(cred_type, "Set your credential")

        params = node.get("parameters", {})
        doc = params.get("documentId")
        if isinstance(doc, dict) and doc.get("value"):
            doc["value"] = SHEET_PLACEHOLDER
            doc["mode"] = "id"
            doc.pop("cachedResultName", None)
            doc.pop("cachedResultUrl", None)
        sheet = params.get("sheetName")
        if isinstance(sheet, dict):
            sheet.pop("cachedResultUrl", None)

    return clean


def scan(clean):
    blob = json.dumps(clean)
    hits = sorted({m for p in SECRET_PATTERNS for m in p.findall(blob)})
    if hits:
        print("Refusing to write: possible live secrets found.", file=sys.stderr)
        for h in hits:
            print(f"  {h[:12]}...", file=sys.stderr)
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--id", help="n8n workflow id to fetch over the public API")
    src.add_argument("--file", help="raw JSON export to sanitize instead")
    ap.add_argument("--output", default=OUTPUT)
    args = ap.parse_args()

    if args.file:
        with open(args.file) as fh:
            wf = json.load(fh)
    else:
        base_url = os.environ.get("N8N_BASE_URL")
        api_key = os.environ.get("N8N_API_KEY")
        if not base_url or not api_key:
            sys.exit("Set N8N_BASE_URL and N8N_API_KEY (see .env.example).")
        wf = fetch(base_url, api_key, args.id)

    clean = sanitize(wf)
    scan(clean)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as fh:
        json.dump(clean, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"Wrote {args.output} ({len(clean.get('nodes', []))} nodes)")


if __name__ == "__main__":
    main()

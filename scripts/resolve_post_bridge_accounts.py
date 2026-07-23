r"""
One-time helper: fetch Post Bridge social account IDs and write them
into config.json's post_bridge.account_ids.

Run from repo root:
    .\venv\Scripts\python.exe scripts\resolve_post_bridge_accounts.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from classes.PostBridge import PostBridge  # noqa: E402


def main() -> None:
    config_path = os.path.join(ROOT, "config.json")
    with open(config_path, "r") as f:
        cfg = json.load(f)

    pb_cfg = cfg.get("post_bridge", {})
    api_key = pb_cfg.get("api_key", "")
    platforms = pb_cfg.get("platforms", ["tiktok", "instagram"])

    if not api_key:
        print("ERROR: post_bridge.api_key is empty in config.json")
        sys.exit(1)

    client = PostBridge(api_key)
    accounts = client.list_social_accounts(platforms=platforms)

    if not accounts:
        print("No linked accounts returned. Check connections in the Post Bridge dashboard.")
        sys.exit(1)

    ids = []
    print("Linked Post Bridge accounts:")
    for acct in accounts:
        acct_id = acct.get("id")
        print(f"  [{acct_id}] {acct.get('platform')} @{acct.get('username', '?')}")
        if acct.get("platform") in platforms and acct_id is not None:
            ids.append(int(acct_id))

    pb_cfg["account_ids"] = ids
    cfg["post_bridge"] = pb_cfg
    with open(config_path, "w") as f:
        json.dump(cfg, f, indent=2)

    print(f"\nWrote account_ids {ids} to config.json — cross-posting is fully wired.")


if __name__ == "__main__":
    main()

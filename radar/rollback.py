"""Prepare an additive rollback in a working tree; never force/reset main.

Stops v2 mechanically, restores old code/prompts, preserves all research/data.
Automation settings are restored separately from the private rollback archive.
"""
import argparse
import json
import subprocess
from pathlib import Path

from radar.engine import Engine

RESTORE = ["aggregate.py", "CHATGPT_RADAR_PROMPT.txt", "schemas/idea-catalog.schema.json",
           "prompts/DISCOVERY_WORKER.txt", "prompts/ORCHESTRATOR.txt", "prompts/MERGE_WORKER.txt",
           "prompts/VALIDATOR_WORKER.txt", "prompts/FINALIZER.txt", ".github/workflows/update-feed.yml"]


def prepare(root, apply=False):
    root = Path(root)
    e = Engine(root)
    e.check_protected()
    baseline = e.read("state/v2/protection/baseline.json")
    commit = baseline["baseline_commit"]
    result = {"baseline_commit": commit, "restore_code_paths": RESTORE,
              "preserve": ["state/idea_catalog.json", "state/idea_history.json", "state/runs", "state/v2", "docs/radar"],
              "mode": "prepare_only", "old_database_sync": "remains_disabled"}
    if apply:
        for name in RESTORE:
            data = subprocess.check_output(["git", "show", f"{commit}:{name}"], cwd=root)
            (root/name).parent.mkdir(parents=True, exist_ok=True)
            (root/name).write_bytes(data)
        config = e.read("state/v2/config.json")
        config["mode"] = "maintenance"
        e.write("state/v2/config.json", config)
        e.check_protected()
        result["mode"] = "working_tree_prepared_no_commit_no_push"
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", default=".")
    p.add_argument("--apply", action="store_true")
    a = p.parse_args()
    print(json.dumps(prepare(a.root, a.apply), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

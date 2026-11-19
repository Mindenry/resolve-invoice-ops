"""Validate labelled evaluation samples and trigger real evaluation runs.

This tool never computes or invents metrics itself: it reads the metrics produced by the
RESOLVE evaluation worker, which are derived from actual provider responses.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx

REQUIRED_KEYS = {"sample_key", "case_context", "expected_exception_types", "expected_root_cause"}


def load_dataset(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "samples" not in payload or not isinstance(payload["samples"], list):
        raise ValueError("Dataset must contain a 'samples' array")
    return payload


def validate_dataset(payload: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    if not payload.get("name"):
        problems.append("Dataset is missing a name")
    seen: set[str] = set()
    for index, sample in enumerate(payload.get("samples", [])):
        missing = REQUIRED_KEYS - set(sample)
        if missing:
            problems.append(f"sample[{index}] missing {sorted(missing)}")
        key = sample.get("sample_key")
        if key in seen:
            problems.append(f"duplicate sample_key {key}")
        seen.add(key)
        if not isinstance(sample.get("expected_exception_types", []), list):
            problems.append(f"sample[{index}].expected_exception_types must be a list")
    return problems


def run_evaluation(
    api: str, email: str, password: str, organization_slug: str, dataset_name: str, run_name: str
) -> dict[str, Any]:
    with httpx.Client(base_url=f"{api.rstrip('/')}/api/v1", timeout=60) as client:
        login = client.post(
            "/auth/login",
            json={"email": email, "password": password, "organization_slug": organization_slug},
        )
        login.raise_for_status()
        auth = login.json()
        headers = {
            "Authorization": f"Bearer {auth['access_token']}",
            "X-Organization-Id": auth["organization"]["id"],
        }
        datasets = client.get("/evaluation/datasets", headers=headers)
        datasets.raise_for_status()
        dataset = next((item for item in datasets.json() if item["name"] == dataset_name), None)
        if dataset is None:
            raise SystemExit(f"Dataset '{dataset_name}' not found. Seed the demo workspace first.")
        created = client.post(
            "/evaluation/runs",
            headers=headers,
            json={"dataset_id": dataset["id"], "name": run_name},
        )
        created.raise_for_status()
        run = created.json()
        run_id = run["id"]
        for _ in range(120):
            detail = client.get(f"/evaluation/runs/{run_id}", headers=headers)
            detail.raise_for_status()
            run = detail.json()
            if run["status"] in {"SUCCEEDED", "FAILED"}:
                break
            time.sleep(2)
        return run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RESOLVE AI evaluation helper")
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate", help="Validate a dataset JSON file")
    validate.add_argument("dataset", type=Path)

    run = sub.add_parser("run", help="Create and poll a real evaluation run")
    run.add_argument("--api", default="http://localhost:8000")
    run.add_argument("--email", required=True)
    run.add_argument("--password", required=True)
    run.add_argument("--organization", default="northwind")
    run.add_argument("--dataset", default="Invoice exception investigations (synthetic)")
    run.add_argument("--name", default=f"CLI run {time.strftime('%Y-%m-%d %H:%M')}")

    args = parser.parse_args(argv)
    if args.command == "validate":
        payload = load_dataset(args.dataset)
        problems = validate_dataset(payload)
        if problems:
            for problem in problems:
                print(f"- {problem}", file=sys.stderr)
            return 1
        print(f"Dataset '{payload['name']}' is valid ({len(payload['samples'])} samples).")
        return 0

    result = run_evaluation(args.api, args.email, args.password, args.organization, args.dataset, args.name)
    print(json.dumps({"status": result["status"], "metrics": result.get("metrics"), "error": result.get("error")}, indent=2))
    return 0 if result["status"] == "SUCCEEDED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
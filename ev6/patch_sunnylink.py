#!/usr/bin/env python3
"""Fail-closed Sunnylink LatAccelFactor step override for the EV6 personal fork.

Change only TorqueParamsOverrideLatAccelFactor's step in the on-device
settings schema (both its YAML source and compiled JSON). This does NOT
patch the separately hosted Sunnylink frontend or its two-decimal UI.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path

YAML_FILE = Path("openpilot/sunnypilot/sunnylink/settings_ui_src/pages/steering.yaml")
JSON_FILE = Path("openpilot/sunnypilot/sunnylink/settings_ui.json")
SETTING = "TorqueParamsOverrideLatAccelFactor"
STOCK_STEP = 0.1
TARGET_STEP = 0.001


def _yaml_updated(text: str, expected: float, replace: bool) -> str:
    # Locate only the item at its list indentation, not unrelated step fields.
    anchors = list(re.finditer(
        rf"(?m)^(?P<indent>[ ]*)- key: {re.escape(SETTING)}[ \t]*$", text
    ))
    if len(anchors) != 1:
        raise ValueError(f"Expected exactly one YAML {SETTING} item, got {len(anchors)}")
    match = anchors[0]
    indent = match.group("indent")
    rest = text[match.end():]
    next_item = re.search(rf"(?m)^{re.escape(indent)}- key: ", rest)
    body_end = match.end() + (next_item.start() if next_item else len(rest))
    region = text[match.end():body_end]
    step_re = re.compile(
        rf"(?m)^[ ]{{{len(indent) + 2}}}step:[ \t]*(?P<value>[0-9]+(?:\.[0-9]+)?)[ \t]*$"
    )
    steps = list(step_re.finditer(region))
    if len(steps) != 1:
        raise ValueError(f"Expected exactly one YAML step for {SETTING}, got {len(steps)}")
    s = steps[0]
    if float(s.group("value")) != expected:
        raise ValueError(
            f"Unexpected YAML {SETTING} step: {s.group('value')}, expected {expected}"
        )
    if not replace:
        return text
    start = match.end() + s.start("value")
    end = match.end() + s.end("value")
    return text[:start] + str(TARGET_STEP) + text[end:]


def _json_items(node: object) -> list[dict]:
    items: list[dict] = []
    if isinstance(node, dict):
        if node.get("key") == SETTING:
            items.append(node)
        for value in node.values():
            items.extend(_json_items(value))
    elif isinstance(node, list):
        for value in node:
            items.extend(_json_items(value))
    return items


def _json_updated(text: str, expected: float, replace: bool) -> str:
    data = json.loads(text)
    items = _json_items(data)
    if len(items) != 1:
        raise ValueError(f"Expected exactly one JSON {SETTING} item, got {len(items)}")
    value = items[0].get("step")
    if type(value) not in (float, int) or value != expected:
        raise ValueError(f"Unexpected JSON {SETTING} step: {value}, expected {expected}")
    if not replace:
        return text

    # Replace only the original numeric literal. Preserve JSON formatting.
    key_re = re.compile(rf'"key"[ \t]*:[ \t]*"{re.escape(SETTING)}"')
    keys = list(key_re.finditer(text))
    if len(keys) != 1:
        raise ValueError("Could not uniquely locate the JSON setting key")
    key = keys[0]
    rest = text[key.end():]
    next_key = re.search(r'"key"[ \t]*:', rest)
    step = re.search(
        r'"step"[ \t]*:[ \t]*(?P<value>[0-9]+(?:\.[0-9]+)?)', rest
    )
    if not step or (next_key and next_key.start() < step.start()):
        raise ValueError("Could not locate the target JSON step before the next key")
    if float(step.group("value")) != expected:
        raise ValueError("Target JSON step literal and decoded value do not match")
    start = key.end() + step.start("value")
    end = key.end() + step.end("value")
    result = text[:start] + str(TARGET_STEP) + text[end:]

    # Assert the entire parsed JSON is identical except for this one value.
    items[0]["step"] = TARGET_STEP
    if json.loads(result) != data:
        raise ValueError("JSON replacement changed unexpected schema fields")
    return result


def process(root: Path, action: str) -> None:
    paths = [root / YAML_FILE, root / JSON_FILE]
    try:
        yaml_original, json_original = [p.read_text(encoding="utf-8") for p in paths]
    except OSError as exc:
        raise ValueError(f"Missing Sunnylink schema: {exc}") from exc

    replace = action == "apply"
    expected = TARGET_STEP if action == "verify" else STOCK_STEP
    new_yaml = _yaml_updated(yaml_original, expected, replace)
    new_json = _json_updated(json_original, expected, replace)

    if replace:
        # Validate both files before writing either of them.
        if yaml_original == new_yaml or json_original == new_json:
            raise ValueError("Sunnylink step patch unexpectedly changed nothing")
        for path, content in zip(paths, (new_yaml, new_json), strict=True):
            path.write_text(content, encoding="utf-8")
        process(root, "verify")
    print(f"{action}: Sunnylink {SETTING} step {'0.001' if action != 'stock' else '0.1'} is valid")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("stock", "apply", "verify"))
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args()
    try:
        process(args.root.resolve(), args.action)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Fail-closed installer for the EV6 on-device torque tuning card (comma 4 / mici UI).

Adds one new module and one guarded block to sunnypilot's mici settings screen.
Before writing anything, check that every upstream name, param key and asset the
card relies on still exists. If upstream moved any of them, stop: do not guess.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
import textwrap
from pathlib import Path

CARD_SOURCE = Path(__file__).resolve().parent / "mici" / "torque_tuning.py"
CARD_FILE = Path("openpilot/selfdrive/ui/sunnypilot/mici/layouts/torque_tuning.py")
CARD_MODULE = "openpilot.selfdrive.ui.sunnypilot.mici.layouts.torque_tuning"
SETTINGS_FILE = Path("openpilot/selfdrive/ui/sunnypilot/mici/layouts/settings.py")
PARAMS_FILE = Path("openpilot/common/params_keys.h")
ASSETS_DIR = Path("openpilot/selfdrive/assets")
PACKAGE_ROOTS = {"openpilot": Path("openpilot"), "opendbc": Path("opendbc_repo/opendbc")}

# The card goes right after "toggles" and "models", ahead of "network".
ANCHOR = "    items.insert(5, sunnylink_btn)\n"
MARKER = "    # EV6 fork: torque tuning card"
BLOCK = (
    "\n"
    f"{MARKER}. A broken card must never take the settings screen down.\n"
    "    try:\n"
    "      from openpilot.selfdrive.ui.sunnypilot.mici.layouts.torque_tuning import TorqueTuningBigButton\n"
    "      items.insert(2, TorqueTuningBigButton())\n"
    "    except Exception:\n"
    "      from openpilot.common.swaglog import cloudlog\n"
    "      cloudlog.exception(\"ev6: torque tuning card unavailable\")\n"
)


def _read(path: Path) -> str:
    # No newline translation: compare exactly what is on disk.
    try:
        return path.read_bytes().decode("utf-8")
    except OSError as exc:
        raise ValueError(f"Missing expected file: {exc}") from exc


def _card_source() -> str:
    # Normalized to LF, whatever line endings this checkout uses.
    return CARD_SOURCE.read_text(encoding="utf-8")


def _defined_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                names.update(n.id for n in ast.walk(target) if isinstance(n, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update((alias.asname or alias.name).split(".")[0] for alias in node.names)
    return names


def upstream_imports(tree: ast.Module) -> dict[str, set[str]]:
    """Every `from openpilot|opendbc... import name`, at any depth."""
    imports: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] in PACKAGE_ROOTS:
            imports.setdefault(node.module, set()).update(alias.name for alias in node.names)
    return imports


def module_path(root: Path, module: str) -> Path:
    top, *parts = module.split(".")
    base = (root / PACKAGE_ROOTS[top]).joinpath(*parts)
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    raise ValueError(f"Upstream module {module} no longer exists")


def _string_constants(tree: ast.Module) -> dict[str, str]:
    constants = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)):
            constants[node.targets[0].id] = node.value.value
    return constants


def param_keys(tree: ast.Module) -> list[str]:
    """Resolve the card's PARAM_KEYS tuple of constant names to key strings."""
    constants = _string_constants(tree)
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "PARAM_KEYS" and isinstance(node.value, ast.Tuple)):
            if not all(isinstance(e, ast.Name) and e.id in constants for e in node.value.elts):
                raise ValueError("PARAM_KEYS may only name string constants")
            return [constants[e.id] for e in node.value.elts]
    raise ValueError("Card does not declare PARAM_KEYS")


def check_upstream(root: Path, card_source: str) -> None:
    """Every name, param and asset used by the card and its settings hook must exist."""
    card = ast.parse(card_source)
    block = ast.parse(textwrap.dedent(BLOCK))
    for tree in (card, block):
        for module, names in upstream_imports(tree).items():
            if module == CARD_MODULE:
                provided = _defined_names(card)
            else:
                provided = _defined_names(ast.parse(_read(module_path(root, module))))
            missing = names - provided
            if missing:
                raise ValueError(f"Upstream {module} no longer provides {sorted(missing)}")

    params_h = _read(root / PARAMS_FILE)
    missing_keys = [k for k in param_keys(card) if not re.search(rf'\{{"{re.escape(k)}",\s*\{{', params_h)]
    if missing_keys:
        raise ValueError(f"Params no longer exist upstream: {missing_keys}")

    icon = _string_constants(card).get("ICON")
    if not icon or not (root / ASSETS_DIR / icon).is_file():
        raise ValueError(f"Card icon asset is missing: {icon}")


def process(root: Path, action: str) -> None:
    settings_path, card_path = root / SETTINGS_FILE, root / CARD_FILE
    settings = _read(settings_path)
    card_source = _card_source()
    check_upstream(root, card_source)

    if action in ("stock", "apply"):
        if settings.count(ANCHOR) != 1:
            raise ValueError(f"Expected exactly one settings anchor, found {settings.count(ANCHOR)}")
        if MARKER in settings or card_path.exists():
            raise ValueError("Torque tuning card is already installed")

    if action == "apply":
        new_settings = settings.replace(ANCHOR, ANCHOR + BLOCK, 1)
        # Validate both files before writing either of them.
        compile(new_settings, str(settings_path), "exec")
        compile(card_source, str(card_path), "exec")
        card_path.write_bytes(card_source.encode("utf-8"))
        settings_path.write_bytes(new_settings.encode("utf-8"))
        process(root, "verify")

    if action == "verify":
        if settings.count(ANCHOR + BLOCK) != 1 or settings.count(MARKER) != 1:
            raise ValueError("Settings screen does not contain exactly one torque card block")
        if not card_path.is_file() or _read(card_path) != card_source:
            raise ValueError("Installed torque card differs from ev6/mici/torque_tuning.py")
        compile(settings, str(settings_path), "exec")

    print(f"{action}: torque tuning card {'is installed' if action == 'verify' else 'can be installed'} in {root}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("stock", "apply", "verify"))
    parser.add_argument("--root", required=True, type=Path, help="Checked-out staging prebuilt")
    args = parser.parse_args()
    try:
        process(args.root.resolve(), args.action)
    except (ValueError, SyntaxError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

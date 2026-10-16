#!/usr/bin/env python3
"""Fail-closed 384/3/7 patch for the two HKG CAN-FD source files.

Only the three numeric assignments in each of these two files may change.
If upstream changes their surrounding structure or original values, stop.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

VALUES_FILE = Path('opendbc_repo/opendbc/car/hyundai/values.py')
SAFETY_FILE = Path('opendbc_repo/opendbc/safety/modes/hyundai_canfd.h')

# The pre-patch state MUST be precisely this tuple. A future upstream change
# requires a human review rather than silently modifying a different tune.
STOCK = (270, 2, 3)
TARGET = (384, 3, 7)

PY_BLOCK = re.compile(
    r'(?m)^    if CP\.flags & HyundaiFlags\.CANFD:\n'
    r'(?P<body>(?:^      [^\n]*\n)+)'
)
C_BLOCK = re.compile(
    r'(?ms)\bHYUNDAI_CANFD_STEERING_LIMITS[ \t]*=[ \t]*\{'
    r'(?P<body>.*?)^[ \t]*\};'
)


def _change_block(content: str, block_regex: re.Pattern[str], keys: tuple[str, ...],
                  values: tuple[int, int, int], replace: bool) -> str:
    matches = list(block_regex.finditer(content))
    if len(matches) != 1:
        raise ValueError(f'Expected exactly one steering limit block, found {len(matches)}')
    block = matches[0]
    body = block.group('body')
    changed_body = body

    for key, expected in zip(keys, values, strict=True):
        assignment = re.compile(
            rf'(?m)^(?P<prefix>[ \t]*{re.escape(key)}[ \t]*=[ \t]*)'
            r'(?P<number>\d+)(?P<tail>[^\n]*)$'
        )
        found = list(assignment.finditer(changed_body))
        if len(found) != 1:
            raise ValueError(f'Expected exactly one {key} assignment, found {len(found)}')
        observed = int(found[0].group('number'))
        if replace:
            old_value = STOCK[keys.index(key)]
            if observed != old_value:
                raise ValueError(f'Unexpected stock {key}: {observed}, expected {old_value}')
            new_value = TARGET[keys.index(key)]
            changed_body = assignment.sub(
                lambda m, value=new_value: m.group('prefix') + str(value) + m.group('tail'),
                changed_body,
                count=1,
            )
        elif observed != expected:
            raise ValueError(f'Wrong {key}: {observed}, expected {expected}')

    if not replace:
        return content
    return content[:block.start('body')] + changed_body + content[block.end('body'):]


def _process_files(root: Path, action: str) -> None:
    paths = (root / VALUES_FILE, root / SAFETY_FILE)
    try:
        originals = [p.read_text(encoding='utf-8') for p in paths]
    except OSError as exc:
        raise ValueError(f'Unable to read expected source files: {exc}') from exc

    replace = action == 'apply'
    expected = TARGET if action == 'verify' else STOCK
    outputs = [
        _change_block(originals[0], PY_BLOCK,
                      ('self.STEER_MAX', 'self.STEER_DELTA_UP', 'self.STEER_DELTA_DOWN'),
                      expected, replace),
        _change_block(originals[1], C_BLOCK,
                      ('.max_torque', '.max_rate_up', '.max_rate_down'),
                      expected, replace),
    ]

    if replace:
        # All checks happen before EITHER file is written.
        for src, dst in zip(paths, outputs, strict=True):
            if src.read_text(encoding='utf-8') == dst:
                raise ValueError(f'Patch was a no-op on {src}')
        for path, text in zip(paths, outputs, strict=True):
            path.write_text(text, encoding='utf-8')
        _process_files(root, 'verify')
    print(f'{action}: {root} has correct CAN-FD steering limit definitions')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('apply', 'verify', 'stock'))
    parser.add_argument('--root', required=True, type=Path,
                        help='Source checkout or checked-out staging prebuilt')
    args = parser.parse_args()
    try:
        _process_files(args.root.resolve(), args.action)
    except ValueError as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

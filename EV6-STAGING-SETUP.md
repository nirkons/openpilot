# sunnypilot staging for Kia EV6 — 384 / 3 / 7

This adds an **automated fork release pipeline** to your own `nirkons/sunnypilot`
repository. The published build is the official sunnypilot `staging` prebuilt
plus the following **two steering source-file edits**, along with a freshly
compiled Panda H7 firmware that includes the C safety-file edit:

| File | Original CAN-FD | Custom CAN-FD |
|---|---|---|
| `opendbc_repo/opendbc/car/hyundai/values.py` | 270 / 2 / 3 | **384 / 3 / 7** |
| `opendbc_repo/opendbc/safety/modes/hyundai_canfd.h` | 270 / 2 / 3 | **384 / 3 / 7** |

The publisher also adjusts Sunnylink's **Lateral Acceleration Factor step**
from `0.1` to **`0.001`** in two UI metadata files:
`openpilot/sunnypilot/sunnylink/settings_ui_src/pages/steering.yaml` and
`openpilot/sunnypilot/sunnylink/settings_ui.json`. Friction remains at
`0.01`. This is a UI step-size change only; it does not change steering
control parameters or initialize a new tuning value.

**Important current Sunnylink frontend limitation:** The separately hosted
website formats floating values using `toFixed(2)`, and its +/- buttons
round to two decimals. This fork **cannot** fix its frontend. With a
`0.001` device schema, the slider may send finer values, but the number
shown in the Sunnylink website and the +/- buttons can be misleading.
A frontend PR to `sunnypilot/sunnylink-frontend` is required for reliable
three-decimal display and button control.

The branch additionally includes `.ev6-build.json` for auditing provenance,
recording both steering limits and the Sunnylink step override.
The binary `panda/board/obj/panda_h7.bin.signed` is **rebuilt every time** from
the exact matching source commit. It is **not** the old 384/4/7 firmware.

## Initial setup

1. Confirm the repository is named [`nirkons/sunnypilot`](https://github.com/nirkons/sunnypilot).
2. Copy the `.github/workflows/ev6-staging.yml` and `ev6/` directory into
   the **default `master` branch** of that repository and push. This release
   script does not have to be part of the published `ev6-staging` branch.
3. In the repo's **Actions** tab, enable GitHub Actions for this fork if
   GitHub asks. Under **Settings → Actions → General**, allow actions and
   permit `GITHUB_TOKEN` workflow writes if GitHub requires it. The workflow
   declares `contents: write`.
4. Open **Actions → EV6 synced sunnypilot staging → Run workflow** and monitor
   its first run. The first run is the build-validation step: **do not install
   an unverified or failed release**.
5. Once the workflow finishes successfully, verify the
   [`ev6-staging` branch](https://github.com/nirkons/sunnypilot/tree/ev6-staging)
   exists and its `.ev6-build.json` records the latest upstream staging SHA
   and the matching Panda binary checksum.
6. On your **comma 4** custom software installer, use:

   `https://install.sunnypilot.ai/fork/nirkons/ev6-staging`

   Do **not** install this URL before the successful first build.

7. Later, use **sunnypilot's normal update controls**. The updater follows
   the fork and branch that was installed. The Panda daemon compares firmware
   signatures and flashes its *matching* bundled firmware if necessary.

## How subsequent updates work

The public fork's standard GitHub Actions runner checks official `staging`
**four times daily** and can be manually triggered. If the upstream staging
commit is unchanged, it exits. If changed, the workflow:

1. Checks out the *exact* upstream staging prebuilt and extracts the matching
   source revision from its release commit message.
2. Checks out that exact source revision and pinned `panda` and `opendbc`
   submodules.
3. Verifies both Hyundai CAN-FD definitions are still stock `270/2/3`.
   If upstream changes them or the file structure, **stop**; do not guess.
4. Applies `384/3/7` to the two source files and compiles H7 Panda firmware
   from the modified safety definition with the pinned toolchain source.
5. Applies exactly those two steering edits and the two guarded Sunnylink
   schema edits (YAML and compiled JSON) to the official staging prebuilt;
   replaces its `panda_h7.bin.signed` firmware artifact.
6. Confirms the two edited steering files match the source files byte-for-byte;
   audits the five expected release-tree differences; publishes an orphan
   `ev6-staging` snapshot in your own repo.

A change to the Sunnylink precision patch triggers a rebuild even if official
staging is unchanged. Changes on `master` to the automation scripts or
workflow trigger an immediate run, in addition to the scheduled checks.

If any step fails (including package incompatibility, changed upstream
structures, compilation, or lack of GitHub write permissions), the existing
release branch is left untouched. **No automatic downgrade or overwrite of a
working release** occurs on failure.

## Boundaries and safety

- This changes **Panda safety-enforced steering limits**, not just UI tuning;
  it is not a vehicle-certified safety profile. It affects the shared HKG
  CAN-FD safety branch, so install it only on your personally tested EV6.
- Successful compilation and automated checks do **not** establish steering
  safety or reproduce months of your real-world driving experience. Review
  any new upstream Panda safety changes and do not update the comma until a
  new firmware version has been validated.
- An upstream change to these exact fields causes a fail-closed build, rather
  than potentially invalid firmware or a silent return to 270/2/3.
- We do not alter `max_rt_delta`, driver torque allowance, steering-request
  checks, or any other safety parameters.
- The first build still needs to be **run on GitHub**. This workflow has not
  been compiled on GitHub's hosted runners or tested on your comma device yet.
- GitHub-hosted standard runners are free for public repositories, subject to
  GitHub's platform rules and repository size/storage constraints. Large
  upstream staging checkouts may exceed a runner's free disk quota; the
  workflow fails rather than publishing an incomplete build.

## Repository uploader (Windows)

If direct GitHub repository write access from ChatGPT is unavailable, use
`Push-EV6-Automation.ps1` from PowerShell on your Windows machine. It copies
these files to a new branch, commits and pushes them, then opens a GitHub PR.
After reviewing, merge the PR into `master` and run the workflow. The uploader
requires Git and authenticated GitHub access (`gh auth login` or a working
Git credential manager); no GitHub token needs to be pasted into ChatGPT.

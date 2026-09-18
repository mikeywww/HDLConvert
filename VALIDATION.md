# Validation record

## 2026-09-18 — Stage 14: Chinese GUI, output encoding and console detachment

- GUI visible text is Chinese and includes an output-encoding selector: GB2312 by default, with GBK and UTF-8 choices. CLI adds `--output-encoding` with the same default and choices; both file APIs use the shared codec validation.
- Frozen GUI uses `FreeConsole` when the console is owned solely by the GUI process. A no-argument EXE launch showed the `HDL 转换工具` window and detached the owned console; shared CLI terminals are not detached.
- `declaration initialization preserved` / `power-up behavior` diagnostics remain in CLI/GUI logs but are no longer injected into generated HDL. The 500-line DDR3 fixture was regenerated without those comments.
- Relevant regression: 30 CLI/HDL/initializer tests passed; 12 conversion tests were run, with a trailing-whitespace-only golden assertion corrected and targeted recheck passed. Native Chinese editor smoke passed. Unrelated passed tests were not repeated per user request.
- Frozen isolated verification passed after the same trailing-whitespace comparison correction. Local EXE: 9,767,655 bytes; SHA-256 `2fa3a3d738307f46b5602d4a1d7f8bd3c3181513d21684d2648ec77757824b5e`.
- This remains a local 2.0.1 candidate. No push, tag, GitHub upload, or Release is authorized yet.

## 2026-09-18 — Stage 13: initializer cleanup, Chinese encodings and local 2.0.1 EXE

- Proven redundant combinational signal initializers are removed without generated comments or diagnostics. Process-variable initializers are removed only when every possible read is preceded by a whole assignment; read-before-write, incomplete branches and partial writes preserve them.
- UTF-8/BOM, GB2312 and GBK source decoding now uses one shared path across CLI, GUI and dependency files; output remains UTF-8.
- Frozen GUI retains the console/`hide-early` hybrid and additionally hides a console owned only by the frozen GUI process. Existing-terminal CLI output remains available.
- `python -m unittest -q`: **72 tests passed** in one complete run after targeted failure correction. `python scripts/verify_release.py`: passed once, including frozen GBK GUI loading.
- Earlier local candidate `dist/HDLConvert.exe`: version 2.0.1; superseded by the current renamed build recorded in RELEASE.md.
- Publication is intentionally paused. Do not push, tag, upload, or create a GitHub Release until the user explicitly approves this candidate.

## 2026-09-18 — HDLConvert 2.0 six-direction upgrade

- Automated suite: **69 tests passed**, including all original VHDL-to-SV regressions and four real Icarus compile/simulation scenarios for the new paths.
- `scripts/validate_six.py`: Vivado compiled original and generated VHDL/SV for all six directions; clock, asynchronous reset, data and blocking combinational ordering matched for 64 cycles.
- `scripts/validate_numeric.py`: original SV and generated VHDL matched for 512 cycles across unsigned overflow, destination-width arithmetic, signed multiply/shift, compare, FSM, generate, module instances, concatenation and replication.
- `scripts/editor_smoke.py`: real Tk/tkdnd loaded; a Unicode/spaced `.sv` path was dropped, language inferred, SV converted to VHDL in the worker thread, highlighting/selection/clear exercised.
- Safety coverage includes continuous semantics for `wire x = expr`, multi/mixed-driver rejection, output preservation on failure, malformed/unsupported source TODO drafts, enum lowering, non-ANSI ports, sized casts, and VHDL initializer width mismatch.
- Passed scenarios were each run once for the final Stage 10 checkpoint; failures were followed by targeted reruns. This matches the user's request to reduce redundant test rounds.
- These are finite regressions, not formal equivalence or evidence of 80% real-project coverage. The README lists the conservative language boundary.

## 2026-09-18 — Stage 11: declaration initializer / driver correction

- Reproduced the old `logic ready_i = 1'b0; assign ready_i = a;` failure with Icarus: “Cannot perform procedural assignment ... because it is also continuously assigned.” Reproducer/log: `build/initializer_before.sv`, `build/initializer_before.log`.
- Added conservative IR analysis for full, non-self-dependent combinational assignments. Stage 13 later changed proven redundant removal to be silent and extended the analysis to process variables.
- `python -m unittest -q`: **50 passed**, including **11 SV compiler/simulation tests**. New coverage: conditional ready expression, per-name declarations, process branch coverage, with-select, whole-array assignments, retained register/constant/variable values, incomplete/partial/generate/feedback cases, case-insensitive scoped names and strict output protection.
- Generated `tests/vhdl/initializer_drivers.vhd` output compiled and simulated successfully; register starts at 1 before any clock and continues to operate after clock edges.
- Vivado 2025.2 synthesis plus `report_drc -checks {MDRV-1}`: **0 errors, 0 critical warnings, 0 MDRV-1 violations**. Explicit post-synthesis assertion confirms register `INIT=1`. One ordinary warning removes unused temporary `v_reg`.
- Reproduce: `python hdlconvert.py tests/vhdl/initializer_drivers.vhd -o build/initializer_drivers.sv`, then `vivado -mode batch -source scripts/validate_initializers.tcl -log build/initializer_vivado.log -journal build/initializer_vivado.jou`.
- Evidence: `build/initializer_vivado.log`, `build/initializer_synth/drivers.rpt`. Marker: `INITIALIZER_SYNTHESIS_PASS`.
- Limit: partial targets, incomplete branches, feedback, generate and instance-bound drivers are not automatically stripped and still require review. This is not a complete multiple-driver/latch analysis.

## Stage 10 baseline

Date: 2026-09-17. Current workspace: `D:\WORK\PRJ\HDLConvert`.

## Automated regression

`python -m unittest -v`: **41 passed**, no skips on this machine.

- Parser nesting, literal/comment tokenization, precedence and malformed input.
- CLI default suffix, generic override, continued processing after failure, destination collision protection, package dependency metadata.
- Array golden output; merge only equal ranges; nonzero/descending/2D bounds.
- Signals/variables, async reset polarity, both clock edges, case/FSM, with-select, package/function, generate/instance.
- Warning paths: unknown identifiers, ambiguous clock structure, differing source/target array ranges, delta-cycle read-after-write, unsupported numeric types, PSL comments. Strict mode and malformed input preserve existing files.
- **10 Icarus compiler/simulation tests**: signed/unsigned resize (all 256 byte values); clock/reset/variable ordering; nonzero and descending 2D array copies; case/slice/concat; package function; mod sign and overflow; intermediate numeric_std overflow/scalar multiplication/negative shift; nested generate with component instances; record/subtype and SV reserved identifier escaping.

`python -m compileall -q hdlconvert gui.py hdlconvert.py scripts tests`: passed.

## Windows GUI

`.venv\Scripts\python.exe scripts/gui_smoke.py`: passed using Python 3.14.5, Tk 8.6 and tkinterdnd2 0.6.3 installed only in the project virtual environment.

Actual Tk and tkdnd Tcl libraries loaded. Tested native-format Tcl drop payload with Chinese/spaced path, deduplication, background conversion, output file and completion count. This is a programmatic drop-event smoke test, not a claim of manual Explorer dragging or visual review.

## Vivado synthesis

Vivado 2025.2, `xc7a35tcpg236-1`, `scripts/validate_vivado.tcl`:

| Source | Result |
|---|---|
| HDLconv original counter converted to SV | 0 errors, 0 critical warnings, 0 warnings |
| Locally authored rtl_demo converted to SV | 0 errors, 0 critical warnings, 4 unused-register optimization warnings |

The four normal warnings remove unused snapshot indices 3/4/5 and count. These are expected because only snapshot(6) and FSM output are observed. Synthesis is not timing closure; no project XDC or implementation run was supplied/requested.

Evidence: `build/vivado.log`, `build/vivado/*_utilization.rpt`, `build/vivado/*.dcp`. Current marker is `HDLCONVERT_VIVADO_SYNTHESIS_PASS`.

## Original VHDL versus generated SV

`python scripts/validate_mixed.py`: **passed**. Vivado xvhdl/xvlog/xelab/xsim compile the original, independently renamed VHDL fixture and the generated SV into one testbench. Outputs match over **256 cycles** with data changes, enable stalls, initial asynchronous reset and another reset during activity.

Evidence: `build/mixed_sim/xsim_captured.log`, marker `MIXED_LANGUAGE_EQUIVALENCE_PASS`.

This is finite simulation of one representative design, not formal equivalence for the language subset.

## External reference fixtures

Read-only survey of 44 top-level VHDL fixture files: 10 converted without warnings, 10 with warnings, 24 rejected; no unexpected Python exceptions. Details: `build/reference_survey.json`.

Many rejected inputs are intentionally incomplete entity-only/architecture-only parser fixtures, malformed VHDL, or require missing packages; others exercise unsupported syntax. These numbers are **not a Vivado project coverage metric**. External clean fixtures include counter, mux, component adder, package enum and simple function examples. Only the external counter was included in full Vivado synthesis verification.

Both reference Git worktrees remained clean. Their code was not copied into the converter implementation.

## Limits of acceptance

Core, CLI, Windows GUI and documented subset are delivered and tested. No actual customer Vivado project was provided, so the requested 80–90% practical RTL coverage goal remains unmeasured. Unsupported constructs and conservative rejections are documented in README; warning outputs require review. No claim of full VHDL/SV semantic equivalence is made.

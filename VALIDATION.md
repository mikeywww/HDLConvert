# Validation record

## 2026-10-02 — Stage 26: VHDL declaration policy and capability audit

- Removed VHDL signal/process-variable declaration initializers in the shared AST preparation. Automatic function-local values now become ordered body assignments; constants, generic defaults and reset statements remain. Removal emits no comments or initialization blocks.
- One full regression run: 95 tests, 93 passed and two assertion mismatches. Corrected the two assertions (parentheses and undriven wire classification); only those two tests were rerun, both passed. No tests skipped.
- Eight actual-file outputs compiled with Icarus: Aurora bridge/top/reset and DDR3, each in Verilog-2005 and SV-2012. Top compilation uses test-only IP shells.
- Vivado mixed-language comparison passed once: original VHDL vs generated V/SV, all Aurora bridge outputs and reset synchronizer, 52,497 cycles including directed malformed-frame/backpressure/overflow/reset scenarios and 12,000 deterministic randomized cycles. A behavioral synchronous RAM model was used; real IP/top behavior was not qualified.
- Scalar-bit numeric increment comparison passed 512 cycles, including two 8-bit wraps. Function `clog2` initialization remains per-call body computation.
- Seventeen original audit fixtures passed Vivado VHDL-2008 analysis. Thirty-four target observations reproduced outstanding conversion/ownership/coverage defects; see AUDIT_REPORT.md. These observations are intentionally not reported as passing regressions.
- Default SV file output was verified to still permit a partial warning module; strict mode rejected it and preserved the existing output. This remains an open issue.
- Logs and generated artifacts: build/audit/. Source project aurora_data_packet was read-only. EXE is still old 2.0.4; no rebuild, push, tag or release performed.

## 2026-09-18 — Stage 16: true windowed EXE and high-DPI GUI

- PyInstaller now uses the Windows `windowed` bootloader (`runw.exe`). GUI launch does not create a console process/window; frozen CLI mode recovers inherited stdout/stderr or attaches to a parent console when possible.
- Direct no-argument launch inspection found exactly one visible top-level window, titled `HDLConvert`, and no console/taskbar companion window.
- GUI enables Per-Monitor V2 DPI awareness before Tk initialization, derives Tk scaling from monitor DPI, uses Microsoft YaHei UI for controls, and chooses a larger screen-aware default geometry capped at 1320×900 with a 900×650 minimum.
- Relevant checks: 7 entry/CLI tests passed; native Tk/tkdnd editor smoke passed; isolated frozen EXE verification passed after one targeted stream-recovery correction.
- Local `dist/HDLConvert.exe`: 9,765,204 bytes; SHA-256 `75edc91ed2406c2713de7d0b3ec6d0e6fed92a548c4f059420f1ee7874004ad7`.
- No source push, v2.0.1 Release, or EXE upload was performed for this stage.

## 2026-09-18 — Stage 15: complete HDLConvert rename

- Renamed the Python package to `hdlconvert`, entry point to `hdlconvert.py`, generated-code branding to `HDLConvert`, Windows product metadata and artifact to `HDLConvert.exe`, and canonical workspace to `D:\WORK\PRJ\HDLConvert`.
- Renamed the public GitHub repository to `mikeywww/HDLConvert`, updated links and remote, and pushed source commit `bafa896` after the rename regression.
- One complete post-rename regression: **73 tests passed**. The new canonical workspace produced the one-file EXE and isolated frozen verification passed.
- Direct frozen launch showed only the `HDLConvert` GUI and detached its owned console.
- Local `dist/HDLConvert.exe`: 9,767,007 bytes; SHA-256 `b48ed4e9829cd1a80369613ddbb520d50dc9ce1ae5fa7350693284dc276d98af`.
- No v2.0.1 GitHub Release or EXE upload was performed; that still requires explicit approval.

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

## VHDL child-port and literal regression (local 2.0.3 candidate)

An external example was fetched for read-only testing from [Parin810's `avalon_interface.vhd`](https://github.com/Parin810/Wavelets-VLSI-Design-/blob/master/1d_wavelet_transform/quartus_demo/avalon_interface.vhd). It contains a component declaration, positional map to child outputs, initialized parent signals and `x"0000"` concatenation. The original was kept only under ignored `build/external/`, not vendored. Direct CLI conversion with `-o build/external/avalon_interface_direct.v` succeeded; the four child-driven signals became uninitialized `wire`, and the literal became `16'h0`. Both generated Verilog-2005 and SystemVerilog-2012 passed Icarus parse/elaboration with a minimal locally written child stub. The source does not connect its final `ready` output; the stub check verifies emitted syntax and binding, not functional equivalence of the third-party project.

The local regression suite passed 81 tests in one run, and the nine focused child-output/literal/fragment cases passed after the final ownership changes. These tests include named/positional maps, direct parent output connection, unknown-interface rejection, a standalone process and `x'0001aa'` width preservation.

The 2.0.3 one-file Windows candidate built successfully at `dist/HDLConvert.exe` (9,780,866 bytes, SHA256 `5253181c3f104d375a1b8c3f7b083f59fed77d1cf153cc20965c04c1bc4b03c4`). One isolated `scripts/verify_release.py` run passed: previous GUI/DnD, GBK, DDR3 and failure-preservation checks plus new child-output and process-fragment EXE checks. This candidate has not been pushed or published.

## Limits of acceptance

HDLConvert 2.0.2 publication check (2026-09-19): the targeted DDR3 VHDL-to-Verilog regression passed, generated Verilog passed Icarus Verilog-2005 parse/elaboration, and the final frozen EXE passed one isolated verification including the DDR3 conversion. Artifact: 9,770,726 bytes; SHA256 `a10d782a233f9332d5e3d7d33aedf10317e1163065d6162b77b58fae317b6496`. The matching artifact was published at GitHub Release v2.0.2.

Final 2.0.1 publication check (2026-09-19): `scripts/verify_release.py` passed once against the final taller-window EXE, including isolated native Tk/tkdnd, GBK input, Unicode paths, conversion directions and failed-output preservation. Prior GUI smoke passed; measured default window height increased from 822 to 878 in the validation environment. Tracked paths and content contain no former project name. Final SHA256: `ee78d904898fbd14982ea81e679662a19f9b3af268403bc68b2d32a1f682c6a5`.

Core, CLI, Windows GUI and documented subset are delivered and tested. No actual customer Vivado project was provided, so the requested 80–90% practical RTL coverage goal remains unmeasured. Unsupported constructs and conservative rejections are documented in README; warning outputs require review. No claim of full VHDL/SV semantic equivalence is made.


## DDR3 interchange repair (local 2.0.4 candidate)

`python scripts/validate_roundtrip.py` generates direct V and SV from the existing 500-line fixture, then V→SV→V, SV→V and V/SV→VHDL. Icarus compiles the Verilog outputs using Verilog-2005 and V→SV using SystemVerilog-2012. Vivado compiles direct SV (Icarus lacks its unpacked default initializer), original VHDL and both generated VHDL designs. A common deterministic bench compares all output ports after reset over 5,000 cycles across eight designs. Results: 208 accepted requests, 104 reads, 103 writes, 6 refreshes, 207 responses and all 20 internal FSM states visited. All comparisons passed. Test products/logs are under ignored `build/roundtrip_validation/`.

This found and fixed time-zero decoder output X, packed-record part-select offset, process-local variable commit and scalar/vector cast issues. Array power-up state and early function return are also covered by focused Icarus simulations. Static zero replications retain exact width; parameter-dependent repetitions are not frozen. Runtime two-state storage and static functions that read retained state are rejected.

One full 91-test regression identified two issues (empty positional associations and an outdated function-lifetime assertion); both were repaired and the two affected tests passed. One further safety regression was added and passed with the affected DDR3 conversion test, bringing the suite to 92 tests without rerunning unrelated cases. Finite simulation does not prove arbitrary language equivalence, reset-free startup, all parameter overrides or board-level DDR behavior.

Final local EXE: 9,799,104 bytes, SHA256 `5987f8e626637f13836ef9723bd335118ce9364d83967e6d89a62deef923a679`. Full isolated verification passed before the final static-state diagnostic guard. After rebuilding with that guard, targeted isolated verification passed for version, GUI PE subsystem, DDR3 reverse conversion and unsafe static-state rejection. Unchanged GUI checks were not repeated. No GitHub upload or Release publication.

## VHDL audit priority repairs — 2026-10-02, local 2.0.5 candidate

Stages 26–29 share the requested declaration policy: no VHDL signal/process-variable declaration initializers, initialization comments or replacement initial blocks. Constants, generic defaults, reset logic and per-call function body initialization remain.

One full regression ran 106 tests (99 passed, 7 failed). Driver checks incorrectly rejected disjoint record fields/complementary generate branches, and old assertions conflicted with newly supported arrays/chains and fail-closed policy. Repairs and targeted rechecks passed; the full suite was not repeated. Three later meaningful behavioral regressions also passed, bringing the suite to 109 tests. Evidence: `build/audit/repair_regression.log`, `repair_recheck.log`, `tests/test_priority_fixes.py`. Icarus was present, not skipped.

Fourteen priority regressions cover V2005/SV2012 compilation and behavioral tests of nonzero/opposite-direction 1D/2D arrays, concurrent positional copies, scalar arithmetic on both sides and indexed increments (520 clocks), multiwidth functions/slices, package types/functions and header parameter scope, partial formal bit order, parent generic fill override, declaration attribute roundtrips, simple delta chains and typed scalar parameter overrides. Failure tests protect existing outputs and reject multiple drivers, unsupported RTL removal, ambiguous partial maps, unproved return widths and static/overridden null ranges.

Latest actual outputs: Aurora bridge/top/reset and DDR3, each converted directly to V and SV (8 files), compile with no conversion diagnostics. Top uses test-only vendor IP interface shells. Original bridge/reset versus the two targets: Vivado passed 52,497 cycles across all bridge outputs, directed frame/backpressure/overflow/reset cases and 12,000 deterministic randomized cycles with behavioral RAM. The separate reset counter passed 512 clocks/two wraps. Evidence: `build/audit/real/`, `build/audit/results.json`, `build/audit/aurora_compare/xsim.log`. This is not real IP/GT top functional verification.

DDR3 Icarus family and Vivado mixed-language checks passed again after the shared ownership/range/parser changes: 5,000 clocks, all outputs, original VHDL and seven translated designs; 208 requests, 104 reads, 103 writes, 6 refreshes, 207 responses, all 20 FSM states. Evidence: `build/roundtrip_validation/`. New partial-formal and generic-fill original audit sources passed xvhdl analysis. No external project source was modified.

Local EXE metadata and isolated frozen result are recorded in RELEASE.md. No push or publication. Finite verification does not prove full language or arbitrary parameter equivalence; complex cases are rejected rather than silently omitted.

Final 2.0.5 artifact: 9,840,105 bytes, SHA256 `25feed702b1dc2706f8080f4f493769405dead3eb09a787f8ee14ed3ca109956`. A full isolated frozen run passed on the initial repaired binary, including the added multiwidth/maps/attributes and incomplete-result file protections. Subsequent GUI-only fixes prevented cursor status from hiding a conversion failure and removed stale saveable output after unexpected worker errors; final frozen targeted version/PE/GUI checks passed, with those cases embedded in `--self-test`. Unaffected conversion checks were not repeated. Evidence: `build/release-verification.log`, `build/release-verification-final.log` and `build/audit/frozen_205.log`.

## RTL fragments — local 2.0.6 candidate

25 new regression tests cover bare case, nested if/elsif/case/loops, multiple assignments, explicit scopes, variable scheduling, declaration prefixes, nonzero arrays, slices/resize, compact literals, multiple processes, omitted initializer names, family snippets, language inference, atomic file protection, startup evaluation and driver/type rejection. 20 affected existing tests passed: parser/expression/clock-reset/process dispatch, SV compiler tests and the unknown numeric-sign boundary. These ran in focused batches, not a new full 134-test run. The first 26-test batch had three failures; enum metadata and slice type proof were fixed, the case bench startup stimulus and target-specific fill assertions were corrected, and only failed/affected tests were repeated.

Icarus Verilog-2005 and SV-2012 compiled and simulated snippets inside actual surrounding scopes: counter increment by `'1'` for 520 clocks including wrap, the case truth table's 8 combinations, typed slice/resize for 256 clocks, and a complete always_comb decoder's startup value. Missing external array element widths and sized-cast signedness are rejected rather than guessed. Cast helper declarations remain outside the process. Vivado xvhdl analyzed four wrapped reverse snippets (conditional, enum case, continuous net initializer and process-local variables). These are finite directed tests; no full language or arbitrary external-context equivalence is claimed.

Real Tk/tkdnd smoke passed Chinese controls, context selection, bare case conversion, clocked multiple assignments, Unicode paths and existing failure safeguards. A Tcl state-object assertion was corrected before the targeted GUI recheck. Frozen isolated checks passed version/GUI PE subsystem/licenses/GUI/DnD/encoding and fragment conversions. An overly specific array loop-name assertion was corrected; only remaining/affected frozen cases were checked afterwards. The final EXE also passed targeted numeric casts, startup lowering, typed reverse conversion, shared-driver and unknown-type rejection, and existing-output protection. Evidence: `build/fragment-tests.log`, `fragment-recheck.log`, `fragment-numeric-check.log`, `fragment-integration-tests.log`, `fragment-cast-recheck.log`, `fragment-init-check.log`, `fragment-final-safety.log`, `fragment-ownership-recheck.log`, `fragment-width-check.log`, `fragment-gui.log`, `fragment-vhdl/`, `release-fragments-recheck.log`, `fragment-frozen-final.log`.

Final artifact: `dist/HDLConvert.exe`, 9,857,018 bytes, SHA256 `13c795b96f88b44c730bb1d2f5cb7ac17b7233436dc494c520fb01d82ce87d18`. No GitHub push/tag/Release. Large DDR3/Aurora comparisons from 2.0.5 were not repeated because this feature changes fragment dispatch and explicit external metadata; complete design clock/reset dispatch and affected expressions were verified. Full always_comb snippets with unproved types/unsupported decoder structure remain conservative Verilog rejections; bare body conversion leaves startup/scheduling to the user's enclosing scope.

## Library headers, Vivado primitives and VHDL comments — local 2.0.7

29 new methods (headers9, primitives9, comments11) and 58 affected existing methods pass through focused batches. The first new26 run passed23, with3 assertion failures in2comment methods (lowercase interface convention and prefix-counting). Corrected only those methods and compiled both commented targets. The affected58 run passed57; the package function whitespace assertion was corrected and only that method repeated. Three additional comment methods cover package/process normalization, selected assignment, and package body/prototype/non-ANSI boundaries. Selected-assignment and package-merge coverage exposed missing comment anchors/metadata; only failed or subsequently modified cases were rechecked. No full163 run; Icarus compilation/simulation checks in these selected tests were available and passed.

All36 catalog entries match the installed read-only Vivado2025.2 VHDL port order/generic types and corresponding Verilog model parameter widths. Explicit UNISIM unknown cells and work-name conflicts fail closed. This catalog is interface metadata, not copied simulation implementation. Library/use text is omitted; supplied package constants/types/functions retain qualified semantic context and unsigned arithmetic still works. Source --/--- comments are rendered at structural positions; no comments are created for removed initializers.

Aurora bridge/top/reset and DDR3 each converted to V/SV, all8 outputs complete without diagnostics and compiled with Icarus. Top IPs use interface stubs, so this is not a physical GT/IP verification. Dedicated actual UNISIM comparison passed original VHDL vs V/SV for64cycles with BUFG, IBUF (boolean string generic), OBUF, FDRE (INIT=1 startup), and LUT2 (4-bit INIT). The first elaboration bound Verilog instances to VHDL models because of library priority; selecting unisims_ver before unisim and explicit1ns/1ps timescale corrected the test environment. Final xelab/xsim passed. Reproducer: scripts/validate_primitives.py. Large historical DDR3/Aurora differential simulations were not repeated.

Single-file Windows GUI EXE2.0.7 isolated verification passed once with only Windows PATH and no Python/Tcl environment: PE/version/licenses/nativeTkDnD, GBK and defaultGB2312, ignored headers, Chinese comment placement, named/template primitive parameters and wire/logic ownership, qualified packages, and old-output protection on unknown primitives. Size9,884,663bytes, SHA256 `93ae42fc7728f663b9e36a4a9b76bc6201480ccaba21a73f170e0929bd240bc3`. No push/tag/Release.

Evidence: build/stage31-new.log, stage31-affected.log, stage31-format-recheck.log, stage31-real.log, build/vivado-primitives/xelab.log, xsim.log, build/stage31-build.log, build/release-stage31.log. Finite validation covers these cases; unlisted RAMB/DSP/GT cells, general library binding and arbitrary comment/format roundtrip through Verilog/SV remain outside the current scope.


## Timescale and actual SV-to-Verilog repair — local 2.0.8

Reproduced automatic SV misclassification from a legal process identifier and adjacent end/if statements; this incorrectly sent a backtick to the VHDL lexer. Added a limited, validated timescale scanner preserving original offsets, per-module inherited metadata, and fragment headers. Opaque strings/comments are not preprocessor input. Unknown directives/macros remain fail-closed.

Ten new directive methods passed in one initial run plus targeted rechecks of two corrected regex assertions, and one additional scope guard. The initial affected batch of36 passed. The subsequent real user SV reproduction failed at unique case, and exposed unsigned integer type loss and straight always_comb startup lowering. Ten new SV methods then passed in9+1 batches, including real-file type/width checks, unsafe case output protection, unsigned high-bit arithmetic and startup/dependency simulations. Nine existing affected methods passed after the comb/type changes. Full discovery now contains183 methods; the full suite was not rerun.

Original tests/sv/aurora_packet_bridge.sv was kept byte-for-byte unchanged. Its generated build/stage32-user/aurora_packet_bridge.v compiled under Icarus Verilog-2005. scripts/validate_sv_bridge.py passed Vivado xvlog/xelab/xsim once: original native SV vs converted V, all19 outputs,698cycles,1396 settled rising/falling-edge comparisons, all3FSM states,18 accepted TX beats,15 backpressure cycles,3 valid/completed frames,6 packet starts,177 length errors,98 keep errors,197 control errors and1 overflow. Before-reset startup outputs also agreed. Small overridden frame/data parameters and behavioral synchronous RAM are used; this is finite RTL regression, not formal equivalence or physical GT/IP qualification. Logs and WDB: build/sv-bridge-compare/.

The initial canonical EXE build could not replace the user's running2.0.7 due to WinError5. No user processes were terminated. Added a safe versioned --name builder option and produced dist/HDLConvert-2.0.8.exe (9,895,722bytes; SHA256243c38ae80cdef7e0e6cdb197f15461a91c57cc87d67d94613c4c0e9962fdebc). Isolated frozen acceptance passed once, with only Windows PATH/no Python/Tcl environment: PE/version/licenses/native GUI/DnD, automatic pasted SV detection, module/fragment timescales and inheritance, BOM/CRLF, actual user SV conversion and port wire/reg ownership, unsigned high-bit V/SV roundtrip, qualified enum safe lowering, and unsafe-case/preprocessing old-file protection. The old dist/HDLConvert.exe remains2.0.7. No push/tag/Release.

Evidence: build/stage32-new.log, stage32-assert-recheck.log, stage32-guard.log, stage32-affected.log, stage32-sv-new.log, stage32-comb-guards.log, stage32-comb-affected.log, stage32-build-versioned.log, build/release-stage32.log. Do not rerun these passing cases unless related code changes.

## Stability closeout — 2026-10-02, working-tree changes after 2.0.8

Created a standard Python 3.14 virtual environment with requirements.txt, independent of the isolated FPGA-tool Python on PATH. scripts/run_tests.py --suite all --require-simulator passed all 190 tests with zero skips, failures or errors. Icarus compiler/simulator were available on PATH, so optional HDL compile/simulation cases ran. Machine-readable evidence: build/test-report.json (local generated artifact; regenerate with the documented runner).

Seven new regressions cover unidentified/invalid source language diagnostics, invalid target argument errors, encoding failure before disk mutation, failed atomic replacement and temporary cleanup, file API preservation, and GUI locked-destination/source-overwrite protection. GUI, six-direction file conversion and legacy dependency conversion now share the same atomic text writer. Comment compilation tests use system temporary storage and find Icarus through PATH instead of a machine-specific path.

Native scripts/editor_smoke.py passed with actual Tcl/Tk and TkDnD: Unicode drop, worker conversion, syntax highlighting, selection, fragment context and incomplete-output save refusal. The isolated embedded Python was deliberately rejected at preflight with exit code 2; evidence: build/isolated-precheck.json. git diff --check passed. No new frozen executable, Vivado differential rerun, push, tag or Release was produced; existing 2.0.8 binary evidence applies only to the previous source snapshot.

## Engineering input context — 2026-10-02, working-tree changes after 2.0.8

The unified file API and historical VHDL file API share package/entity context resolution. Explicit package dependencies are order-independent, header/body files may be separate, and named search directories discover transitive unit-name files. Duplicate package/entity definitions, package cycles, ambiguous directory matches and missing search directories fail closed. Package body imports are now included in SystemVerilog symbol resolution. Dependency entities supply only interface metadata; dependency package definitions are not duplicated into every SV module output.

Thirteen new project methods passed. Full scripts/run_tests.py --suite all --require-simulator passed 203 methods with zero failures/errors/skips (build/project-test-report.json). Cross-file BASE/TYPES packages and main/child/parent outputs compiled and simulated under Icarus Verilog-2005 and SystemVerilog-2012, checking all sampled data/child outputs. Regressions also cover literal file-list path handling, mixed-success JSON reports with source lines, strict-warning report retention, unchanged old outputs on context errors, and batch-input/report overwrite protection. After directory-index caching and protected-path precomputation, only the affected thirteen project methods were rechecked; all passed.

Native editor_smoke.py passed after the API/context changes. A persistent three-input CLI example using file lists and arbitrary-named metadata files converted all three designs with no warnings/failures; inspect build/project-example/conversion-report.json and build/project-example/converted/. README and DEVELOPMENT_PLAN.md document compile ordering, metadata-only dependencies and remaining scope. Final git diff --check passed. No frozen EXE rebuild or new Vivado differential run was performed, and no remote publication occurred.

## Corpus-driven coverage and four-state repairs — local 2.1.0

The checked-in corpus manifest contains five repository files/cases, two correlated DDR3 derivatives and three synthetic probes, totaling twenty directional attempts and seven distinct physical input files. Baseline conversion completed sixteen attempts. Packed reductions and bounded concurrent concatenated-target lowering raised completion to nineteen; Icarus/GHDL checks passed for all nineteen generated outputs. The remaining native Aurora SV-to-VHDL attempt still rejects $clog2; later source-line context fixes correctly locate it at line47. This is measured sample completion, not customer coverage. Icarus compilation and GHDL VHDL-2008 analysis are not behavioral equivalence, and the generic corpus evaluator explicitly records equivalence=not_run.

IEEE2008 std_logic_1164 unary and/or/xor map packed-bit reductions to std_logic; negated aliases and logical packed !/&&/|| retain four-state results. Boolean/integer/unpacked reductions remain rejected. Fixed-width whole-signal concurrent concat targets use positional extraction; procedural, partial, duplicate, symbolic-width and user-function-RHS cases fail closed. A discovered ownership gap was repaired by recursively collecting every concatenation leaf for V/SV declarations and all-target mixed-driver checks.

Independent original Verilog-2005/SystemVerilog-2012 Icarus traces and generated VHDL GHDL traces agree on2568 rows: exhaustive four-state data at WIDTH1/4/5 in each source mode, plus ascending fixed ranges/scalars, signed operands, result widening, repeated/sliced parity, concat target positions, sign extension/truncation and packed logical operations. Generic reduction defaults also compile in entity scope. Initial tests revealed one incorrect expectation (an unpacked port was rejected at its missing array-type context before reaching reduction validation); its fixture was changed to an internal unpacked array to test the intended boundary. Affected tests then passed. Full219 methods passed after coverage changes; a later source-line regression increased final discovery to220, all passed in final release-source regression with zero skips. Logs: build/corpus-baseline.json, corpus-final.json, coverage-test-report.json, release-source-test-report.json.

Built dist/HDLConvert-2.1.0.exe with Python3.14, Tcl8.6, PyInstaller6.22.3 and pinned build requirements. Size9,908,457bytes; SHA256 `a7313219e7669a90c113cfe3268d303853f918a1399041c25892c2ce436b6e82`. PE GUI subsystem/version, CLI/version/licenses/native TkDnD, Chinese/GBK paths, file lists, unordered dependencies, metadata-only SV packages, transitive directory discovery, JSON/error-line reporting and unchanged old outputs on context failure passed in isolated scratch storage with Windows-only app PATH and no Python/Tcl environment. Default acceptance also passed fragments, legacy array golden output, DDR3 conversion chain, child ownership and audit refusal cases. The frozen EXE itself generated the VHDL used for a fresh2568-row differential check; host simulators ran with their own environment, independent of the app's restricted PATH. Retained trace evidence: build/frozen-four-state-2.1.0/. Acceptance logs: build/release-2.1.0.log and stage34-verification.log. Artifact metadata/source hashes: build/release-2.1.0.json; build log: build/stage34-build.log.

Finite validation does not prove arbitrary four/nine-value expressions, parameter overrides, full scheduling or physical IP behavior. No new Vivado large differential simulation, formal proof, Git push, tag or Release publication occurred. Existing2.0.8 records remain historical evidence for that snapshot.
# 2026-10-02：DDR3 cast 清理 / 2.1.1

- `scripts/run_tests.py --suite all --require-simulator --require-vhdl-simulator`：230 项通过，无失败/错误/跳过（`build/cast-test-report.json`）。新增测试覆盖 DDR3 输出、参数覆盖边界、溢出、嵌套尺寸转换、符号扩展及 X/Z。
- `scripts/validate_roundtrip.py --stage prepare` 后 `--stage family`：Verilog-2005/SV 四条链编译及 5000 周期对照通过；208 次接受、207 次响应、全部状态覆盖。本次不宣称原 VHDL 混合语言等价性。
- 冻结 2.1.1 在 System32-only PATH 下生成 DDR3 Verilog，与源码 API 文本一致，转换 helper 7→2，Verilog-2005 编译通过；`build/cast-frozen-ddr3/report.json`。
- `scripts/verify_release.py --exe dist/HDLConvert-2.1.1.exe --engineering`：隔离 PE/版本/许可/原生 GUI、依赖/搜索/文件列表/JSON/失败保护、诊断及 2568 行四态对照通过；`build/cast-frozen-verification.log`。

## 2026-10-02：保留 DDR3 选择分支编写逻辑 / 2.1.2
原 selected assignment 被过度改写成 hdl_select(...value_0,...value_11)。现在分支常量直接赋给 debug_state_decode，case 标签、others、时间零求值保留；无法安全内联的动态表达式继续显式作为函数输入。DDR3 无 value_* 和 hdl_cast_*，计数表达式恢复为 next_count = {1'b0, completed} + 33'd1。常量尺寸和无符号扩展直接生成常量或拼接；一般截断/符号/参数相关转换仍保留必要边界。
231 项回归无失败/错误/跳过。新增 time-zero/X/Z/default/dynamic-branch 检查通过；Icarus 及 Vivado 原 VHDL/译后 Verilog/SV 混合语言 5000 周期对照通过；冻结 2.1.2 原生 GUI/工程/四态验收、DDR3 API 输出一致性/Verilog-2005 编译通过。有限仿真不代表全域形式等价。日志和候选 hash 见 RELEASE.md。当前候选 dist/HDLConvert-2.1.2.exe；开发目录 D:\WORK\PRJ\HDLConvert；旧 EXE/现有未提交修改保留，未推送或发布。

## 2026-11-27：老项目平台迁移 M1–M3 验证记录

- `.\.venv\Scripts\python.exe scripts/run_tests.py --suite all --require-simulator --require-vhdl-simulator`：**254 项全部通过**（0 失败 / 0 错误 / 0 跳过），包括新增 `tests/test_migration_features.py` 22 项 Icarus/GHDL 编译与行为仿真测试，以及全部 43 个 Vivado 2025.2 UNISIM 原语接口与 Verilog 模型核对（`tests/test_primitives.py`）。
- `.\.venv\Scripts\python.exe scripts/evaluate_corpus.py tests/corpus/manifest.json --compile --report build/m3-corpus-final.json`：13 样本、26 次六向转换尝试 **26/26（100%）** 完整转换并通过 Icarus (`-g2005`/`-g2012`) / GHDL (`--std=08`) 编译检查，含原唯一阻塞样本 `tests/sv/aurora_packet_bridge.sv → VHDL` 及新增 `sync_fifo.sv`、`reg_bank.v`、`legacy_alu.vhd`。
- `.\.venv\Scripts\python.exe scripts/validate_sv_bridge.py --vhdl build/m1-bridge-vhdl/aurora_packet_bridge.vhd --work build/m1-sv-vhdl-compare`：Vivado 2025.2 `xvlog`/`xvhdl -2008`/`xelab`/`xsim` 混合语言对照 **PASS**——原生 SV 与生成 VHDL 在覆盖参数下 698 周期、1,396 次上升/下降沿比较、全部 19 个输出端口 100% 一致（覆盖 3 种 FSM 状态、18 拍 TX、15 周期背压、3 完整帧、177 length/98 keep/197 control 错误与 1 次溢出）。有限仿真不代表全域形式等价；尚未重新打包 2.2.0 EXE，未推送或发布。

# Development progress

## Completed: stability closeout

- Shared atomic output for editor, neutral file API and historical file API.
- Consistent source-identification diagnostics from the six-direction text API.
- Standard-runtime preflight and core/GUI/all regression entry with JSON evidence.
- Portable comment compilation tests, failure-preservation regressions and native Tk smoke.

## Completed: engineering inputs

- Shared VHDL package/entity dependency metadata for both Verilog targets.
- Package dependency ordering, separate header/body files, explicit ambiguity/cycle rejection.
- Source-directory and explicit search-directory discovery using unit-name basenames.
- Literal CLI file lists and per-file JSON diagnosis reports, including strict-write refusals.
- Protection against batch outputs overwriting another input.
- Cross-file package and parent/child compilation and behavioral regression for both targets.

Current scope: each input produces its own output. Dependency module RTL and SV package definitions must be converted separately. No hierarchy bundling, complete library binding, SV include/macro support or automatic global elaboration is claimed.

## Completed: first evidence-driven coverage iteration

- Corpus evaluator records six-direction denominators, origin groups, input/context hashes, code snapshot and optional compiler evidence; behavioral equivalence is explicitly separate.
- Initial checked-in corpus: 5 repository examples, 2 correlated derived cases, 3 synthetic probes. Completion increased from 16/20 to 19/20 attempts; all 19 generated outputs passed available analysis/compilation.
- Packed-bit reductions and logical truth/negation preserve four-state results in VHDL-2008. Integer/array/boolean reductions remain conservative rejections.
- Fixed-width whole-signal concurrent concatenation targets lower positionally; procedural/partial/parameter-width/function-RHS cases remain rejected. All concat leaves now participate in driver ownership across targets.
- Differential Icarus/GHDL regression compares 2,568 exhaustive four-state trace rows across both inputs at widths 1/4/5, including reductions, logical operations, sign extension and truncation.
- VHDL backend error diagnostics retain declaration/statement lines; the native Aurora blocker is now correctly located at line 47.

## Next: measured remaining gaps

1. Native Aurora SV→VHDL requires a semantic plan for $clog2, unsigned 32-bit parameter arithmetic and override-dependent ranges before lowering the system function. Do not freeze defaults or infer safety from the converted V variant.
2. Extend the measured corpus with supplied independent RTL projects; retain repository/probe/derived grouping. Current counts cannot estimate customer coverage.
3. Add source-located diagnostic codes and editor navigation when the chosen extension requires richer feedback.
4. Expand verified RAMB/DSP primitive metadata only with interface/model evidence and targeted simulation.

## Completed: local candidate handoff

- Independent dist/HDLConvert-2.1.0.exe, shared CLI/acceptance version and matching PE metadata.
- Final source regression:220 tests passed with zero skips; isolated frozen default acceptance passed.
- New frozen engineering/report/error-line checks and2568 independent four-state trace comparisons passed.
- Artifact size/SHA256, source hashes, build runtime, test evidence and remaining limitations recorded in RELEASE.md and build/release-2.1.0.json.
- Candidate is local only; no push, tag or public Release.

Each extension must retain explicit refusal when width, signedness, scheduling or ownership cannot be established. The2.1.0 binary has its own build/isolated acceptance; previous2.0.8 records remain historical.

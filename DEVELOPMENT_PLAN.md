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

## Completed: Legacy-Migration M1–M3 Iteration (2026-11-27)

Target: practical six-direction synthesizable RTL interchange (`VHDL ↔ SystemVerilog ↔ Verilog`) for legacy FPGA/ASIC project platform migration.

- **M1 (Parameterized SV/Verilog → VHDL)**:
  - `$clog2(...)` lowered via pure synthesizable `hdl_clog2(n : natural) return natural` (auto-emits entity helper package `<mod>_hdl_pkg` when `$clog2` appears in generics/ports, otherwise in architecture); negative `$clog2` fails closed; untyped `parameter`/`localparam` initialized from `$clog2`/`$bits`/integer arithmetic infers `integer`.
  - `int unsigned` parameters/localparams map to VHDL `natural` with static 31-bit (`0..2^31-1`) overflow rejection; runtime `int unsigned` ports/signals/locals map to `unsigned(31 downto 0)`.
  - Scalar `std_logic` dynamic indexing (`bank_ready[sel]`, `bank_ready[sel] <= 1'b1`), symbolic-width vector + scalar/integer arithmetic & comparisons via `hdl_max`, symbolic `[0:N-1]` memory array bounds, clean `(\reset_n\ = '0')` async reset idiom, and `to_unsigned` for known non-negative constants (eliminating GHDL truncation warnings).
  - Native `tests/sv/aurora_packet_bridge.sv → VHDL` now converts with zero diagnostics, passes GHDL VHDL-2008 analysis with zero warnings, and passes **Vivado 2025.2 mixed-language SV-vs-VHDL simulation** (`scripts/validate_sv_bridge.py --vhdl`): 698 cycles, 1,396 comparisons across all 19 outputs with overridden generics (`DATA_WIDTH=16`, `PACKET_WORDS=3`, `PACKETS_PER_FRAME=2`, `BANK_ADDR_WIDTH=3`, `RAM_ADDR_WIDTH=4`).
- **M2 (High-Frequency Verilog/SV RTL Features)**:
  - Indexed part-select `sig[base +: W]` and `sig[base -: W]` across V↔SV↔VHDL (both descending and ascending vectors, verified in Icarus & GHDL).
  - `casez` with `?`/`z` wildcards preserved in V↔SV and lowered to locally-static VHDL-2008 `case?` with `'-'` don't-care bits (assumes synthesizable non-Z selector); `casex` preserved in V↔SV and conservatively rejected for VHDL.
  - Procedural compound assignments `+=` / `-=` (rejected on concurrent `assign`), procedural concatenation targets (`{carry, sum} <= a + b`, atomic `{a, b} = {b, a}` via single-evaluation process temporary `hdl_concat_*`), static disjoint bit-slice/field multi-process driver checking across all targets, and `` `default_nettype none `` / `` `default_nettype wire `` directive support (other nettypes still rejected).
- **M3 (Legacy VHDL Migration Features & Verified Vivado Primitives)**:
  - VHDL `buffer` port mode mapped to `output`, `ieee.std_logic_signed.all` + `conv_integer` / `conv_std_logic_vector` / `conv_unsigned` / `conv_signed` (rejecting conflicting `std_logic_unsigned` + `std_logic_signed`), `for i in sig'range` / `'reverse_range` loops & generates, and static `case` range choices (`when 0 to 3 =>`).
  - Verified Vivado 2025.2 primitive catalog expanded from 36 to **43** cells (`+IDDR`, `ODDR`, `IDDRE1`, `ODDRE1`, `IDELAYCTRL`, `MMCME2_BASE`, `PLLE2_BASE`), with `'real'` generic support and `'L'`/`'H'` pulldown default handling, all 43 verified against installed `unisim_VCOMP.vhd` and `unisims/*.v`.
- **Verification**:
  - Full regression `scripts/run_tests.py --suite all --require-simulator --require-vhdl-simulator`: **254/254 passed** (0 failures, 0 errors, 0 skips).
  - Expanded corpus (`tests/corpus/manifest.json`: 13 samples, 26 directional attempts including `sync_fifo.sv`, `reg_bank.v`, `legacy_alu.vhd`): **26/26 converted and compiled cleanly** (Icarus Verilog-2005 / SV-2012 + GHDL VHDL-2008).

## Next: M4 Roadmap (Platform Migration Engineering Depth)

1. **Verilog/SV source comment preservation**: preserve module/declaration/statement/inline comments across `V ↔ SV` and `V/SV → VHDL` (matching VHDL comment anchoring).
2. **SV `package` / `import pkg::*;` & V/SV multi-file dependency context**: extend `--dependency` / `--search-dir` beyond VHDL-only input so multi-file Verilog/SV projects resolve packages and child module interfaces cleanly.
3. **Additional legacy VHDL constructs**: `generate` with local declarations & `elsif/else generate`, positional/named vector aggregates (`(7 downto 4 => a, others => '0')`, LHS `(a, b) <= expr`), signal-slice `alias`, and compact width inference for `integer range 0 to N`.
4. **Additional verified Vivado RAMB/DSP primitives**: verify `RAMB18E1`, `RAMB36E1`, `DSP48E1`, `DSP48E2` against installed Vivado 2025.2 UNISIMs and add targeted Vivado mixed-language simulation.
5. **Expanded real-project corpus & next local EXE candidate (2.2.0)**: validate on supplied customer legacy RTL projects and package/verify updated local EXE when ready (no push/tag/release without explicit user permission).

## Completed: local candidate handoff

- Independent dist/HDLConvert-2.1.0.exe, shared CLI/acceptance version and matching PE metadata.
- Final source regression:220 tests passed with zero skips; isolated frozen default acceptance passed.
- New frozen engineering/report/error-line checks and2568 independent four-state trace comparisons passed.
- Artifact size/SHA256, source hashes, build runtime, test evidence and remaining limitations recorded in RELEASE.md and build/release-2.1.0.json.
- Candidate is local only; no push, tag or public Release.

Each extension must retain explicit refusal when width, signedness, scheduling or ownership cannot be established. The2.1.0 binary has its own build/isolated acceptance; previous2.0.8 records remain historical.

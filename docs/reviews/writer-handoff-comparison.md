# Writer handoff comparison · 2026-11-06

The G5 planning changes did not drop a supplied rank order in the controlled case below. An order written as a customer convention survived both handoff routes. In the HP02 run, the approved plan specified a rank-to-weight lookup, but its six customer conventions and single weights convention did not assign ranks to individual indicators. These observations do not determine why the model chose to keep reading.

## Comparison boundaries

- G5 planning J1 through J3: `d5e7406` (parent of J1) to `5509f74` (G5 release).
- Later Writer change: `01fa1ac` (pre-W1 rescue baseline) to `f89068b` (fresh object-scoped Writer). The published fixture and probe code baseline is `de18575`.
- Each revision ran its own archived source on independent copies of the same approved business data per comparison. We called the production `delegated_task` context and inspected the returned Writer description. Where the compact route exists, we also invoked the registered `read_assignment` tool. No model or network requests. A legacy Writer could request other information later; this comparison covers the handoff, not everything the application could read.

## Control with a supplied order

The repository's synthetic four-indicator commission supplied a 30 m slope, an approved method and a section assignment. We imported a supplemental customer document reading “Design prevails over survey. Customer indicator ranks: D=1, C=2, B=3, A=4.” Its exact source citation and interpretation were added to the plan. The historical Coordinator checkpoint approved this synthetic plan once on a temporary fixture. Separate runs used the same files, frozen plan and fresh task call with the same description.

| Revision and route | Actual public result |
|---|---|
| `d5e7406`, section delegation | Exact customer order and precedence in the 1,394-character Writer description |
| `5509f74`, section delegation | Byte-identical description to the pre-J1 run |
| `f89068b`, object-scoped Writer | Both instructions in the assignment tool result as customer conventions, four indicator definitions, one inventory attribute and four rank weights |
| `de18575`, object-scoped Writer | Same measured fields as W1. No structured assigned rank on the indicator rows |

The frozen control plan payload SHA-256 was `16afd39d9054455965a278a1548624d08791158136638f314747434a897c6a05`. The two section delegation descriptions both hashed to `c25ff4d8cf1eae7b4c0f08fa4c2c27b80dc1f84e402d6f5acd80d4d1e88ebc79`. Recreating a new synthetic commission generates new object IDs. Compare digests **within the paired run**.

## Historical HP02 case

The business-only importer copied the approved plan v2 and source versions, blocks and original blobs into temporary storage, excluding previous task history. Independent copies received the same fixed HP02 section goal. The experiment read the returned descriptions and tool results without inspecting model reasoning.

| Revision | Measured result on HP02 |
|---|---|
| `d5e7406` | Pre-J1 confirmation rejects the later G5 plan with `COMMISSION_REQUIREMENTS_INCOMPLETE`; there was no Writer handoff under this combination |
| `5509f74` and `01fa1ac` | Identical section Writer descriptions. Both included design-over-survey priority and the section source locators for pages 96 and 20. The descriptions did not include the complete grade definitions or a structured rank assignment |
| `f89068b` and `de18575` | Each compact assignment conveyed four slope inventory attributes, all 44 grade descriptions, two sources with candidate pages, source priority and eleven rank weights. Neither included per-indicator assigned ranks |

Plan payload digest `4c2b095311433779c1d990bd02fbee61eab7babb69a259a1e963f9093ed099ac`. Business state `dae8cd0c590485ae216dbdcff0d1071e6f1f5ebaf03ac82f62f3830e232d214a`; source versions `14c85875bf32d4ccc727b332699de44a413f254b525459d1b693a8bdd2976407`; source blocks `c84caad9dcd963c07ebede0dc23cb799c4b114520aa9c9f2a3c67f9b5e70404a`. The two historical section descriptions shared SHA-256 `af8f1db36d1686c6ed7a831d68d877836813021971551ee3ec63af4906f3c0f6`. A rank weight tells the system how to weight a rank; it does not assign an indicator to that rank.

## Recurring regression

`PYTHONPATH=src python -B -m pytest -q tests/test_writer_handoff_comparison.py` passed (1 test). It checks both current handoff routes with a real imported synthetic customer document, including quotation and locator on the compact result. The historical comparisons above used archived revisions, separately from this ordinary regression. This comparison holds the plan constant, so it does not evaluate differences in plans produced by different model-led planning runs.

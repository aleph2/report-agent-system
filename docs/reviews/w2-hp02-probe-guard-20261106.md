# HP02 guarded probe implementation

Owner authority: the revised W1 review of 2026-11-05, approved in chat. This increment implements the prerequisite guard and exactly one HP02 probe. The execution stops afterward, including on success. Other slopes, prose cleanup and export require the next allocation decision. G5 and the prior rescue remain stopped and unchanged.

The end-to-end acceptance target is one fresh Writer task using the approved business snapshot and the existing assessment tool. The system binds the canonical HP02 identity (`HP-02-K1323p670-L`), plan/decision, sources, tool operations and indicator labels. The Writer remains responsible for engineering judgments; scores and comments remain system outputs.

## Money and launch boundaries

- A lexical `RequestBound` reduces only this trusted request's reservation. It does not edit global authorization or the existing 2M model bound.
- The documented GLM-5.3 ceilings, input 1,048,576 plus output 131,072, reserve 1,179,648 per request. This is conservative model-ceiling accounting, not a tokenizer certificate or measured input fit. The configured generation setting remains 65,536.
- Model, approved service/environment hashes, exact final request URL, output limit, single completion, nonstreaming and text-only payload are checked before reservation and dispatch.
- The post-reservation observer enforces 1.5M settled plus held for HP02 and the shared 20M rescue cap. An over-limit current request is recorded as known-not-sent; previous unknown outcomes retain their full holds. Original baselines are persisted once, never reset.
- The trusted operator launcher uses an exclusive receipt and lock, disables SDK/connection/recovery retries, and starts only a new single-slope assessment task. A saved canonical assessment stops it before another model call. Every terminal outcome requires owner review, without automatic continuation.

## Independent inputs and capability

The importer constructs a new allowlisted business database from an owning-Linux read-only SQLite snapshot. It preserves approved identities, verified source text/catalog and required original source blobs. It imports no old checkpoints, model recovery/control state, tasks, operations, observations, events or outputs. Historical carryover origins remain provenance only. Its dependency manifest and import receipt describe the new execution's inputs. The old-source-unavailable test covers in-process file/SQLite access, not an operating-system sandbox.

The configured GLM Writer is text-only. Its page tool supplies native text and mechanical tables without images, visual handles or image-read credit. Drawing-only evidence remains `SYSTEM_VISUAL_CAPABILITY_UNAVAILABLE`; it cannot be called absent or visually verified. The one probe is diagnostic and does not establish full drawing verification or engineering acceptance. Image-capable callers retain their existing page behavior.

## Verification and review

New tests cover wire refusal before HTTP, nested recovery/observer scopes, exact caps, preserved holds and authorization, independent business import, actual SDK serialization with MockTransport, exact canonical identity, a single launch, native tool refusals and terminal receipts. The corrected canonical-ID fixture reproduces the pre-send selector failure; the launcher now uses the approved identity throughout.

Independent Neo review found the alias/canonical-ID launch bug (P1 for this probe) and a misleading final reservation field (P2). Both were corrected before any paid request. Detailed source hashes, test results, baseline comparisons, launch and probe results are retained in the owner-authorized monitoring evidence.

The accepted baseline's two legacy DeepAgents summary/checkpoint failures remain deferred; this fresh plain-create_agent path does not use that factory. They are not claimed fixed. No new dependencies, environment edits, global finance changes or old-checkpoint repair are part of this increment.

## Operator entrypoint

After trusted preparation, verified authority, persisted financial baselines, documented request proof and fresh-business import have been bound in the execution's own evidence directory:

```sh
python -B -m report_agent.writer_probe --case OWNED_ROOT/case --evidence OWNED_ROOT/evidence --env APPROVED_ENV
```

The command is not an agent tool and does not grant additional spending or a second launch. Its terminal receipt records the assessment reference, safe exact refusal codes, observed metrics, finance totals and preserved hold. A terminal receipt is inspected, never replayed.

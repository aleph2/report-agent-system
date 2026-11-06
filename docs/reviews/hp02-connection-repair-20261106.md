# HP02 connection recovery repair — 6 November 2026

The two HP02 probes stopped during fresh TLS handshakes. Their clients used a
five-second idle expiry and the probe required both retry layers off. This repair
reduces repeated handshakes and tolerates bounded connection-establishment
failures. It does not establish the underlying cause of the historical TLS errors.

The shared sync/async client factories now retain idle connections for 60 seconds,
keeping 100 total and 20 idle connections, certificate verification and timeouts.
The same Limits object reaches clients and prebuilt transports. The default
async path keeps native environment-proxy routing. Global retry defaults and
SDK opt-ins outside the probe are unchanged.

Future HP02 operator launches must explicitly set `REPORT_CONNECT_RETRIES=2`
and `REPORT_SDK_RETRIES=0`; other policies are refused before model construction.
The receipt records both counts, keepalive expiry and pre-HTTP retry scope.
HTTPX/httpcore supplies the existing native retry loop: at most three connection
attempts before the HTTP request. No custom retry executor or semantic workflow
was added. After-send read/write failures and HTTP 500 do not replay the model call.
Old operator scripts and run records remain historical; this repair does not
change or re-run them and grants no new paid launch authority.

## Verification

221 unique offline tests passed across 59 focused and 194 broader checks
(the reports overlap). Tests use the actual configured GLM/SDK/client pools and
replace only the network backend: TLS retries then one POST and body, one ledger
reservation/settlement, one logical invocation; exhaustion and post-send errors
are covered. Cap/authority/hold, SDK opt-in, timeout, tracing and client-lifecycle
checks passed. The broken-write fixture follows native early-response behavior
and supplies a broken response stream; production retry logic was not altered
to satisfy the fixture.

The 2,499-row real ledger and authorization, every historical hold, Writer sources
and unrelated working-tree changes are unchanged. No provider/model call or
new probe was made. Main and an independent alignment reviewer examined the
final diff and evidence. Full application regression was not repeated; live
stability, historical TLS root cause and Writer judgment quality remain unverified.

Implementation: `deep_models.py` and `writer_probe.py`; tests:
`test_connect_retry_policy.py` and `test_writer_probe.py`.
Evidence was retained in the local monitor's `hp02-connection-repair-20261106` directory.

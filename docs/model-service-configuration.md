# Model service configuration

`load_mixed_services(env_file)` reads a complete URL, model name and API key bundle
from `HIGHWAY_MODEL_DEEPSEEK_NAME`, `HIGHWAY_MODEL_DEEPSEEK_BASE_URL` and
`HIGHWAY_MODEL_DEEPSEEK_API_KEY`. The user-specified file is read, never rewritten.
Coordinator, reviewer, text tools, vision and grader services use this same bundle.
The separate `HIGHWAY_MODEL_*` bundle continues to supply the GLM writer and layout.

Compatible DeepSeek endpoints retain their configured URL and model name. They do
not inherit the official API's `/beta` endpoint or strict tool wire protocol.
Alibaba Model Studio uses `enable_thinking`; the official DeepSeek API adapter keeps
its existing provider-specific protocol. See the [Model Studio API documentation](https://help.aliyun.com/en/model-studio/deepseek-api).

Loading configuration and constructing clients does not call a model. It does not
restart or resume a report. Saved executions retain their original service identities;
the existing resume guard prevents silently changing an old run's bound services.
Diagnostics may record model identity and safe configuration checks, never API keys.

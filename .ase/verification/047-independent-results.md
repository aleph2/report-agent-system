# Task047：同Aliyun连接切换DeepSeek的独立复核

2026-09-30。独立评审者 `/root/llm_rl_expert`，仅写本文件；不发起调用、邮件或新实验，不读密钥及私有reasoning，不修改其他文件。沿用042冻结oracle，SHA256 `f09f6e5acaf08a3db2e96784e8f7dabf522397d2ef3c9a653f54b35215f4a3c7`，未改。

## 结果前的轻量核验

已读Task047与新运行器，直接比较046/047保存request：system/user及tools完全相同；只变模型为`deepseek-v4.1-flash`、GLM thinking对象换成`enable_thinking=true`、`max_completion_tokens`换成`max_tokens=65536`。required、high、parallel_tool_calls false及stream false不变。运行器保留同一Aliyun URL/key读取来源、direct SDK、retry0和一次调用，不改变生产或运行043。没有读取密钥值，也不凭同一读取来源声称已核验密钥字节。

system/user SHA256分别为`d167b3c571860b9501f1b0d95bb6bc05476c9267bc880c826b11aba2f8356293`、`68504cfd4871eda5210dfdd19e26e8a880df22066721028a682067e68dc07c39`；request SHA256为`e74acca7566078d81af8b1b739a5eeb8664493bc3afaeb575eaea02fa648ffe9`。模型适配差异明确存在；不是严格只改一个字段，也不以high标签保证不同后端内部预算相同。

本次只评固定输入的单次响应，不证明模型稳定优势、提示稳定效应或原生主干/G1通过。相对045还存在端点和工具选择等差异，045协议失败不能删除。当前未见需要阻断该限定观察的准备输入问题，实际输出待Main通知后复核。

## 评分口径

依042 oracle分别检查O1采用易滑软弱分类时70与75～100的条件矛盾、O2现有降雨前提下100的规则支持、O3真实高度未知与确定分档缺乏支持；关系、C2/overall、误拒、修复充分性和权限分开。其余五标准没有完整gold。不扩展数值复算；协议失败不修补后计成功，未表达不推断内部不懂，usage子项不重复累计。

## 运行后结果

**用户取消等待，本次未完成、不可评分。** Main通知已按用户要求向本地本次Python进程PID 2275244发出SIGTERM，原执行session退出1；该操作事实由Main记录，本评审未另行操作进程。

独立检查原目录：没有`response.json`或`output.json`；原receipt仍为`attempted`，model_requests=1、model_responses=0、usage=null、max_retries=0，没有ended。它是终止前保存的执行记录，不能将其改解释为模型已返回失败。Main将另存取消记录并保留原receipt；本次检查时`cancellation.json`尚未出现，不声称已独立核验该新文件。

无公开回答，因此O1/O2/O3、C2/overall、误拒、修复质量和输出协议均**不可评分**。退出码1在此是本地用户取消后的终止结果，不证明服务端调用失败、模型能力不足或输出协议错误。请求可能已经到达服务端，但服务端状态和实际计费用量未知；usage缺失不记零，也不据此认定未计费。

本次不产生模型成败样本、不删去尝试、不自动重试、不将取消列为确认bug。用户另选官方服务后的新请求应属于另一个独立尝试，不能覆盖047或补称047完成。本评审仅收尾已有记录，未发邮件、调用模型或开展新实验。

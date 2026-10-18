# 安装框架的提示与摘要默认值

日期：2026-10-17。读取实际WSL虚拟环境的已安装源码，不启动Agent或模型。版本号不能单独证明安装内容与上游完全一致；本册另保存文件hash。

## 当前实际追加关系

- 项目注册openai HarnessProfile，没有设置base_system_prompt或system_prompt_suffix；其默认值为None。当前框架不会因为graph.py中仍存在LEGACY_BASE_AGENT_PROMPT就自动追加该旧提示。
- 安装的DeepAgents 0.7.19在graph.py说明：文件系统／subagent默认不再重复追加整段工具使用prose，工具说明和可用Agent列表主要进入tool schema。不能把默认tool description算作必然存在于system message中的文字。
- Coordinator显式使用TodoListMiddleware，其系统提示见下文。Writer／Reviewer／Layout没有在项目middleware列表中显式加入TodoListMiddleware，不能由Coordinator推断所有角色都有该系统提示。
- FilesystemMiddleware当前项目没有提供自定义system_prompt，使用StateBackend和所声明六种文件工具；它不是无约束host文件或shell访问。
- 当前build_agent没有传skills或memory，不能宣称框架已自动加载项目SKILL.md或所有历史反馈。
- stateful报告路径排除框架默认SummarizationMiddleware，改用项目WorkingSummary，但复用框架的摘要默认计算函数。Learner的独立构建另行配置，不能默认照搬报告上下文。
- 下面原文含未被当前角色调用的模板部分；如read_file模板中的格式占位符，由框架依实际工具和backend填入。它不是完整provider请求。

## 摘要触发值

安装函数compute_summarization_defaults的逻辑是：模型profile含整数max_input_tokens时，trigger为fraction 0.85，keep为fraction 0.10；无该profile时trigger为170000 tokens，keep为最近6条messages。项目working_summary使用这个trigger/keep，另设输出上限16384、提示目标约1200 tokens。这些数值分别是触发、保留和输出目标，不能混为一谈，也不是Codex应用自身设置。


## WRITE_TODOS_SYSTEM_PROMPT

适用性：Coordinator显式TodoListMiddleware系统提示。

安装来源：/home/dysun/.venvs/report-agent-system/lib/python3.12/site-packages/langchain/agents/middleware/todo.py:119，版本1.4.2。

~~~~text
## `write_todos`

You have access to the `write_todos` tool to help you manage and plan complex objectives.
Use this tool for complex objectives to ensure that you are tracking each necessary step.
This tool is very helpful for planning complex objectives, and for breaking down these larger complex objectives into smaller steps.

It is critical that you mark todos as completed as soon as you are done with a step. Do not batch up multiple steps before marking them as completed.
For simple objectives that only require a few steps, it is better to just complete the objective directly and NOT use this tool.
Writing todos takes time and tokens, use it when it is helpful for managing complex many-step problems! But not for simple few-step requests.

## Important To-Do List Usage Notes to Remember

- The `write_todos` tool should never be called multiple times in parallel.
- Don't be afraid to revise the To-Do list as you go. New information may reveal new tasks that need to be done, or old tasks that are irrelevant.

## Finishing a task

When you finish all work, write your final answer in the message AFTER your last `write_todos` call — not in the same turn as that call. Start the final message with the substantive content the user asked for — the data, computation, summary, or analysis. The user wants the result, not confirmation that the work is done.
~~~~

## WRITE_TODOS_TOOL_DESCRIPTION

适用性：todo工具描述。

安装来源：/home/dysun/.venvs/report-agent-system/lib/python3.12/site-packages/langchain/agents/middleware/todo.py:52，版本1.4.2。

~~~~text
Use this tool to create and manage a structured task list for your current work session. This helps you track progress and organize complex tasks.

Only use this tool if you think it will be helpful in staying organized. If the user's request is trivial and takes less than 3 steps, it is better to NOT use this tool and just do the task directly.

## When to Use This Tool

Use this tool in these scenarios:

1. Complex multi-step tasks - When a task requires 3 or more distinct steps or actions
2. Non-trivial and complex tasks - Tasks that require careful planning or multiple operations
3. User explicitly requests todo list - When the user directly asks you to use the todo list
4. User provides multiple tasks - When users provide a list of things to be done (numbered or comma-separated)
5. The plan may need future revisions or updates based on results from the first few steps

## How to Use This Tool

1. When you start working on a task - Mark it as in_progress BEFORE beginning work.
2. After completing a task - Mark it as completed and add any new follow-up tasks discovered during implementation.
3. You can also update future tasks, such as deleting them if they are no longer necessary, or adding new tasks that are necessary. Don't change previously completed tasks.
4. You can make several updates to the todo list at once. For example, when you complete a task, you can mark the next task you need to start as in_progress.

## When NOT to Use This Tool

It is important to skip using this tool when:
1. There is only a single, straightforward task
2. The task is trivial and tracking it provides no benefit
3. The task can be completed in less than 3 trivial steps
4. The task is purely conversational or informational

## Task States and Management

1. **Task States**: Use these states to track progress:
    - pending: Task not yet started
    - in_progress: Currently working on (you can have multiple tasks in_progress at a time if they are not related to each other and can be run in parallel)
    - completed: Task finished successfully

2. **Task Management**:
    - Update task status in real-time as you work
    - Mark tasks complete IMMEDIATELY after finishing (don't batch completions)
    - Complete current tasks before starting new ones
    - Remove tasks that are no longer relevant from the list entirely
    - IMPORTANT: When you write this todo list, you should mark your first task (or tasks) as in_progress immediately!.
    - IMPORTANT: Unless all tasks are completed, you should always have at least one task in_progress.

3. **Task Completion Requirements**:
    - ONLY mark a task as completed when you have FULLY accomplished it
    - If you encounter errors, blockers, or cannot finish, keep the task as in_progress
    - When blocked, create a new task describing what needs to be resolved
    - Never mark a task as completed if:
        - There are unresolved issues or errors
        - Work is partial or incomplete
        - You encountered blockers that prevent completion
        - You couldn't find necessary resources or dependencies
        - Quality standards haven't been met

4. **Task Breakdown**:
    - Create specific, actionable items
    - Break complex tasks into smaller, manageable steps
    - Use clear, descriptive task names

Being proactive with task management ensures you complete all requirements successfully
Remember: If you only need to make a few tool calls to complete a task, and it is clear what you need to do, it is better to just do the task directly and NOT call this tool at all.

## When You Finish

`write_todos` tracks your work; it does not deliver the answer. Whatever the user asked for — computations, summaries, comparisons, data — must appear as text content in a message after your final `write_todos` call. Marking the last todo complete is not itself an answer to the user.
~~~~

## TASK_TOOL_DESCRIPTION

适用性：task工具模板；available_agents由实际注册角色填入。

安装来源：/home/dysun/.venvs/report-agent-system/lib/python3.12/site-packages/deepagents/middleware/subagents.py:463，版本0.7.19。

~~~~text
Launch an ephemeral subagent to handle a complex, multi-step task.

Available agent types and the tools they have access to:
{available_agents}

Specify subagent_type to select the agent. Usage notes:
- Launch multiple agents concurrently when their tasks are independent, using a single message with multiple tool calls.
- Each invocation is stateless by default: the agent sees only the prompt you give it and returns a single final report. Put full detail in the prompt and state exactly what it should return — unless an agent type below says it inherits your conversation instead.
- The agent's report is not shown to the user; relay a summary yourself.
- Tell the agent whether to create content, analyze, or only research, since it can't necessarily see the user's intent unless it inherits your conversation, as noted per agent type below.
- If an agent's description says to use it proactively, do so without waiting to be asked.
- When only general-purpose is available, use it for any complex, context-heavy task; it has the same capabilities as the main agent.
~~~~

## LIST_FILES_TOOL_DESCRIPTION

适用性：ls工具描述。

安装来源：/home/dysun/.venvs/report-agent-system/lib/python3.12/site-packages/deepagents/middleware/filesystem.py:1315，版本0.7.19。

~~~~text
Lists all files in a directory.

This is useful for exploring the filesystem and finding the right file to read or edit.
You should almost ALWAYS use this tool before using the read_file or edit_file tools.
~~~~

## _READ_FILE_TOOL_DESCRIPTION_TEMPLATE

适用性：read_file模板；含动态格式字段。

安装来源：/home/dysun/.venvs/report-agent-system/lib/python3.12/site-packages/deepagents/middleware/filesystem.py:1320，版本0.7.19。

~~~~text
Reads a file from the filesystem. Assume any path the user provides is valid; reading a missing file returns an error.

Usage:
- {first_line}. Use `offset`/`limit` to page through large files instead of reading them whole.
- A status header, `@@ field | field | ... @@`, sits above the file content, and every line after it is verbatim file content. When content is truncated, there may be an explanation before the header. Never include the header when editing.
- Speculatively batch multiple `read_file` calls in one response when several files may be useful.
- An empty file returns a system-reminder warning in place of contents.
- Large tool results may be offloaded to a file; the tool message gives the path. Read that path here, paging with `offset`/`limit`.
- Images (`.png`, `.jpg`, etc.), audio, video, and PDFs return multimodal content blocks (https://docs.langchain.com/oss/python/langchain/messages#multimodal).
{multimodal_bullets}
- Always read a file before editing it.
~~~~

## EDIT_FILE_TOOL_DESCRIPTION

适用性：edit_file工具描述。

安装来源：/home/dysun/.venvs/report-agent-system/lib/python3.12/site-packages/deepagents/middleware/filesystem.py:1354，版本0.7.19。

~~~~text
Performs exact string replacements in files.

Usage:
- You must read the file before editing; this tool errors otherwise.
- Preserve the exact source indentation from the read output, and never include the read status header in old_string or new_string.
- Prefer editing an existing file over creating a new one.
- Only use emojis if the user explicitly requests it.
~~~~

## WRITE_FILE_TOOL_DESCRIPTION

适用性：write_file工具描述。

安装来源：/home/dysun/.venvs/report-agent-system/lib/python3.12/site-packages/deepagents/middleware/filesystem.py:1363，版本0.7.19。

~~~~text
Writes content to a file. Creates the file if it does not exist; replaces it entirely if it does.

Usage:
- Use this tool when you intend to create a new file or replace the whole file. You do not need to read the file first.
- Prefer to edit existing files (with the edit_file tool) over creating new ones when possible.

~~~~

## GLOB_TOOL_DESCRIPTION

适用性：glob工具描述。

安装来源：/home/dysun/.venvs/report-agent-system/lib/python3.12/site-packages/deepagents/middleware/filesystem.py:1379，版本0.7.19。

~~~~text
Find files matching a glob pattern, returning absolute paths.

Supports `*` (any characters within a path segment), `**` (any directories), `?` (single character), `[abc]` (one character from a set), and `{a,b}` (alternatives), e.g. `*.py`, `src/**/*.py`, `*.{yml,yaml}`.

A pattern without `/` matches the file name at any depth under the search root (`*.py` matches `src/app/main.py`). A pattern containing `/` matches the search-root-relative path (`src/**/*.py`). A leading `/` anchors to the search root (`/*.py` matches only top-level Python files).

Leading-dot names are only matched when the pattern segment itself starts with `.` (use `.env`, or `.github/**/*.yml`). Because `**` will not descend into dot-directories, the bare form `*.yml` is *broader* than `**/*.yml` and is usually what you want.
~~~~

## _GREP_TOOL_DESCRIPTION_TEMPLATE

适用性：grep模板；含动态格式字段。

安装来源：/home/dysun/.venvs/report-agent-system/lib/python3.12/site-packages/deepagents/middleware/filesystem.py:1391，版本0.7.19。

~~~~text
Search for a LITERAL text pattern across files (NOT regex).

The pattern is matched verbatim: regex metacharacters are ordinary characters, not operators. To match any of several strings, run a separate grep for each; `grep(pattern="foo|bar")` searches for the literal text "foo|bar", and `.*` or `\.` match those characters literally.{execute_fallback}

Returns matching files or content per `output_mode`. Offloaded large tool results live under the artifacts root (`/large_tool_results/` by default); grep that directory to search them when you do not know the exact path.
~~~~

## 摘要默认计算函数原文

~~~~python
def compute_summarization_defaults(model: BaseChatModel) -> SummarizationDefaults:
    """Compute default summarization settings based on model profile.

    Args:
        model: A resolved chat model instance.

    Returns:
        Default settings for trigger, keep, and truncate_args_settings.
            If the model has a profile with `max_input_tokens`, uses
            fraction-based settings. Otherwise, uses fixed token/message counts.
    """
    has_profile = (
        model.profile is not None
        and isinstance(model.profile, dict)
        and "max_input_tokens" in model.profile
        and isinstance(model.profile["max_input_tokens"], int)
    )

    if has_profile:
        return {
            "trigger": ("fraction", 0.85),
            "keep": ("fraction", 0.10),
            "truncate_args_settings": {
                "trigger": ("fraction", 0.85),
                "keep": ("fraction", 0.10),
            },
        }

    # Defaults for models without profile info are more conservative to avoid
    # overshooting context limits.
    return {
        "trigger": ("tokens", 170000),
        "keep": ("messages", 6),
        "truncate_args_settings": {
            "trigger": ("messages", 20),
            "keep": ("messages", 20),
        },
    }
~~~~

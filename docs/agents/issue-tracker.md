# Issue tracker: GitHub

本项目使用 [yb2915722928-cpu/rag_me](https://github.com/yb2915722928-cpu/rag_me) 统一托管代码、Issues 和 Pull Requests。需求、缺陷、规格和拆分任务记录在该仓库的 GitHub Issues；本地草稿作为工作材料，发布后以 GitHub Issue 为准。

## 仓库定位

固定目标仓库为 yb2915722928-cpu/rag_me，默认分支为 main。Git 的 origin 指向 https://github.com/yb2915722928-cpu/rag_me.git。

使用 Git 管理本地代码，使用 GitHub CLI（gh）操作事项和 PR。每条 gh issue 或 gh pr 命令都显式传入 --repo yb2915722928-cpu/rag_me；gh api 的接口路径也必须包含该仓库，避免在其他工作目录或 worktree 中操作错误仓库。

## 代码协作

- 开始任务前检查本地修改和远端更新，从最新的 main 创建任务分支。分支名使用 feat/<事项编号>-<简述>、fix/<事项编号>-<简述> 或 docs/<事项编号>-<简述>；未关联事项的维护工作可省略编号。
- 在任务分支提交并推送代码：`git push --set-upstream origin <分支名>`。
- 创建 PR：`gh pr create --repo yb2915722928-cpu/rag_me --base main --head <分支名> --title "标题" --body-file <正文文件>`。正文说明变更行为和验证结果；完成事项时写 Closes #<事项编号>，只完成部分工作时写 Refs #<事项编号>。
- 查看 PR：`gh pr view <编号> --repo yb2915722928-cpu/rag_me`。评审与合并以 GitHub PR 为协作入口。
- 运行时凭据保存在本地环境变量或被忽略的环境文件中；仓库只保留不含真实凭据的示例。

## 常用操作

- 创建事项：`gh issue create --repo yb2915722928-cpu/rag_me --title "标题" --body-file <正文文件>`。多行正文保存到临时 UTF-8 文件，并通过 --body-file 传入。
- 读取事项：`gh issue view <编号> --repo yb2915722928-cpu/rag_me --json number,title,body,labels,comments`。
- 列出未关闭事项：`gh issue list --repo yb2915722928-cpu/rag_me --state open --json number,title,body,labels,comments`，按需要添加 --label、--state 等过滤条件。
- 添加评论：`gh issue comment <编号> --repo yb2915722928-cpu/rag_me --body-file <正文文件>`。
- 添加或移除标签：`gh issue edit <编号> --repo yb2915722928-cpu/rag_me --add-label "标签"`，或使用 --remove-label。
- 关闭事项：`gh issue close <编号> --repo yb2915722928-cpu/rag_me`。需要记录结论时，先添加评论。
- 创建子事项：支持时使用 `gh issue create --repo yb2915722928-cpu/rag_me --parent <父事项编号> ...`，或 `gh issue edit <父事项编号> --repo yb2915722928-cpu/rag_me --add-sub-issue <子事项编号>`。若不可用，在子事项正文开头记录 Part of #<父事项编号>，并在父事项任务列表中链接子事项。

技能要求“publish to the issue tracker”时，创建 GitHub Issue；要求“fetch the relevant ticket”时，读取指定事项及相关讨论。

## Pull requests as a triage surface

**PRs as a request surface: no.**

GitHub 的 Issue 与 PR 共用编号空间。仅提供编号而类型不明时，先用 `gh pr view <编号> --repo yb2915722928-cpu/rag_me` 识别 PR，再回退到 gh issue view。

## Wayfinding operations

供 wayfinder 使用；只在实际运行该工作流时建立所需事项和标签。

- Map 是带 wayfinder:map 标签的单个 Issue，正文包含 Notes、Decisions-so-far、Fog。
- Child ticket 是 Map 的子事项，类型标签为 wayfinder:research、wayfinder:prototype、wayfinder:grilling 或 wayfinder:task；不支持子事项时使用父事项任务列表与 Part of 引用。
- Blocking 优先使用 GitHub 原生 Issue dependencies。通过 `gh api --method POST repos/yb2915722928-cpu/rag_me/issues/<子事项编号>/dependencies/blocked_by -F issue_id=<阻塞事项数据库ID>` 建立依赖；数据库 ID 通过 `gh api repos/yb2915722928-cpu/rag_me/issues/<阻塞事项编号> --jq .id` 获取，不能使用事项编号或 node_id 代替。不支持原生依赖时，在正文开头使用 Blocked by: #<编号> 引用；全部阻塞事项关闭后才可开始。
- Frontier 按 Map 中的顺序选择第一个未关闭、没有未解决依赖且尚未分配的子事项。优先检查 issue_dependencies_summary.blocked_by；回退时读取正文中的依赖引用。
- Claim 在开始工作前执行 `gh issue edit <编号> --repo yb2915722928-cpu/rag_me --add-assignee @me`。
- Resolve 先评论回答，再关闭子事项，最后将结论摘要和链接追加到 Map 的 Decisions-so-far。

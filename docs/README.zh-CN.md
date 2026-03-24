# Tasklane 中文说明

Tasklane 是一个面向单机实验工作流的本地命令调度器。

它保留原始命令不变，把任务写入本地 sqlite 队列，按 CPU / GPU 资源规则调度执行，并把输出持续回传到当前终端。

## 适合解决什么问题

- 把任意 shell / Python 命令注册进本地队列
- 区分 GPU 任务、CPU 重任务、CPU 轻任务
- 避免 GPU 或整机资源被错误抢占
- 保持默认前台阻塞、可观察、可取消的终端体验
- 在需要时用一个本地 daemon 持续处理队列

## 资源类别

- `gpu-exclusive`
  - GPU 任务，可以与轻量 CPU 工作并发
- `gpu-host-exclusive`
  - 既占 GPU，又需要独占主机 CPU / 内存 / IO 的任务
- `cpu-exclusive`
  - CPU 或内存重任务，占用整机 host-exclusive 资源
- `cpu-light`
  - 轻量 CPU 任务，例如评估、汇总、报告生成

当前内置资源容量：

- `gpu-0 = 1`
- `host-exclusive = 1`
- `cpu-light = 150`

## 安装

### Windows

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install-windows.ps1
```

### Linux

```bash
bash ./scripts/install-linux.sh
```

也可以直接通过 GitHub 安装：

```powershell
uv tool install git+https://github.com/bainianlaoyao/tasklane.git
```

```bash
uv tool install git+https://github.com/bainianlaoyao/tasklane.git
```

## 快速开始

### 1. 初始化本地状态

预览：

```powershell
tasklane-bootstrap
```

执行初始化：

```powershell
tasklane-bootstrap --apply
```

默认状态目录：

- Windows: `%LOCALAPPDATA%\tasklane`
- Linux: `~/.local/share/tasklane`

也可以通过 `TASKLANE_HOME` 覆盖：

```powershell
$env:TASKLANE_HOME = "D:\Data\Tasklane"
```

### 2. 提交一个前台任务

```powershell
tasklane `
  --cwd E:\freqtrade `
  --project tabicl `
  --resource gpu-exclusive `
  --run-name tabicl-ra-001 `
  -- uv run python user_data/tabicl_pipeline/generate_random_anchor_predictions.py
```

默认行为：

- 先注册任务
- 本地立即尝试调度
- 在当前终端等待完成
- 持续输出 stdout / stderr
- 返回子进程真实退出码

典型输出：

```text
[scheduler] submitted run_id=... queue=gpu resource=gpu-exclusive
[scheduler] waiting run_id=... state=queued queue=gpu
[scheduler] started pid=12345
loading data...
epoch 1/10
[scheduler] finished status=completed exit_code=0
```

### 3. 运行 daemon

如果你需要处理 detached 任务或想让多个终端共用一个队列，可以运行：

```powershell
tasklane daemon
```

## 查看当前队列

当前快照：

```powershell
tasklane queue
```

终端持续刷新：

```powershell
tasklane queue --watch
```

JSON 输出：

```powershell
tasklane queue --json
```

这个视图会直接显示：

- 任务总数和状态统计
- 当前资源占用
- 每个任务的状态、资源类别、PID、退出码、运行时长、命令摘要

## 前台与 detached

默认模式是前台 attach。

只有在你明确需要“提交后立刻返回”时，才使用 `--detach`：

```powershell
tasklane `
  --cwd E:\freqtrade `
  --project tabicl `
  --resource cpu-exclusive `
  --detach `
  -- uv run python train.py
```

注意：

- detached 任务本身不会自动推进
- 需要有一个 attach 提交者或 `tasklane daemon` 在处理队列

## 状态模型

Tasklane 不依赖 Prefect。

运行时状态保存在本地：

- sqlite 数据库
- 每个任务单独的日志文件

其中包括：

- 提交的命令与元数据
- 当前任务状态
- 取消请求状态
- 退出码
- 调度器事件和命令输出日志

## 兼容命令

为了兼容旧脚本，以下入口仍然可用：

- `pcs`
- `pcs-bootstrap`
- `prefect-submit`
- `prefect-bootstrap`

它们都会映射到同一个本地 Tasklane 调度器。

## 开发与验证

```powershell
uv sync --group dev
uv run --group dev pytest
uv tool install -e . --force
tasklane --help
tasklane-bootstrap --help
tasklane queue
```

## 相关文档

- English README: [../README.md](../README.md)
- Skill 安装说明: [./SKILL-INSTALL.md](./SKILL-INSTALL.md)
- Agent skill 文件: [../SKILL.md](../SKILL.md)

# Tasklane Skill Install Guide

This repository includes a reusable agent skill file:

- [SKILL.md](../SKILL.md)

Use it when you want an AI coding agent to understand how to operate Tasklane without re-explaining the workflow each time.

## What the skill covers

- Tasklane runtime state model
- resource classes and queue semantics
- standard bootstrap and worker workflow
- attached CLI behavior
- important boundaries for safe usage
- verification commands

## Option 1: Use the file directly from this repository

If your agent can read a skill file by path, point it at:

```text
<repo>/SKILL.md
```

Example on Windows:

```text
D:\Data\DEV\tasklane\SKILL.md
```

Example on Linux:

```text
/home/<user>/tasklane/SKILL.md
```

This is the simplest option when you are actively developing Tasklane in the same checkout.

## Option 2: Install as a personal Codex skill

Create a dedicated skill directory under your Codex skills folder and copy `SKILL.md` into it.

Typical location:

```text
~/.agents/skills/tasklane/SKILL.md
```

Windows PowerShell:

```powershell
$target = Join-Path $HOME ".agents\\skills\\tasklane"
New-Item -ItemType Directory -Force -Path $target | Out-Null
Copy-Item .\SKILL.md (Join-Path $target "SKILL.md") -Force
```

Linux:

```bash
mkdir -p ~/.agents/skills/tasklane
cp ./SKILL.md ~/.agents/skills/tasklane/SKILL.md
```

After that, Codex can load the skill by name when the task matches Tasklane usage.

## Option 3: Install as a personal Claude Code skill

Claude Code typically looks for personal skills under:

```text
~/.claude/skills/tasklane/SKILL.md
```

Windows PowerShell:

```powershell
$target = Join-Path $HOME ".claude\\skills\\tasklane"
New-Item -ItemType Directory -Force -Path $target | Out-Null
Copy-Item .\SKILL.md (Join-Path $target "SKILL.md") -Force
```

Linux:

```bash
mkdir -p ~/.claude/skills/tasklane
cp ./SKILL.md ~/.claude/skills/tasklane/SKILL.md
```

## Updating the installed skill

When `SKILL.md` changes, copy it again to your personal skills directory.

Codex example:

```powershell
Copy-Item .\SKILL.md "$HOME\\.agents\\skills\\tasklane\\SKILL.md" -Force
```

```bash
cp ./SKILL.md ~/.agents/skills/tasklane/SKILL.md
```

Claude Code example:

```powershell
Copy-Item .\SKILL.md "$HOME\\.claude\\skills\\tasklane\\SKILL.md" -Force
```

```bash
cp ./SKILL.md ~/.claude/skills/tasklane/SKILL.md
```

## Verifying the install

The easiest check is to ask the agent to use the `tasklane` skill while working inside a repository that uses Tasklane.

You can also verify the file exists in the expected location:

Windows PowerShell:

```powershell
Get-Item "$HOME\\.agents\\skills\\tasklane\\SKILL.md"
Get-Item "$HOME\\.claude\\skills\\tasklane\\SKILL.md"
```

Linux:

```bash
ls ~/.agents/skills/tasklane/SKILL.md
ls ~/.claude/skills/tasklane/SKILL.md
```

## Recommendation

If you only use Tasklane in one checkout, use the repository-local `SKILL.md` directly.

If you want the skill available across projects, install it into your personal skills directory and update it when Tasklane changes.

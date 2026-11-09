# Skills 目录说明

这个目录存放所有可用的 Agent Skill。

## 目录结构

```
.agents/skills/
├── code-review/          # Skill 1：代码审查
│   └── SKILL.md
├── writing-assistant/    # Skill 2：写作助手
│   └── SKILL.md
└── your-skill-name/      # 你的 Skill
    └── SKILL.md
```

## 如何创建新 Skill

1. 在 `.agents/skills/` 下新建一个文件夹，名字就是 Skill 的标识
2. 在文件夹里创建 `SKILL.md` 文件
3. 文件开头用 YAML Frontmatter 声明元信息：

```markdown
---
name: your-skill-name
description: 这个 Skill 是做什么用的，什么时候应该使用它
---

# 你的 Skill 正文

这里写 Skill 的详细说明、使用方式、指南等。
```

## 规范要求

- `name`：必需，Skill 的唯一标识，用英文小写加连字符
- `description`：必需，简要描述 Skill 的功能和使用场景
- `SKILL.md`：必需，每个 Skill 目录至少包含这一个文件
- 初始化时只加载 `name` 和 `description`，不读取完整正文
- 需要使用 Skill 时，按需加载完整内容

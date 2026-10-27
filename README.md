# 去 AI 味视觉审查

审查已经存在的网页或代码动画，去掉模板感，并直接做最小代码修复。它不是“把所有东西变极简”，而是让文案、容器、颜色、字号、焦点和动效各自有明确职责。

## 它解决什么

- 页面像说明书：标题上有一行装饰英文，副标题复述标题。
- 每个数字都套卡片：圆角、阴影、渐变边、玻璃效果层层叠加。
- 颜色没有语义：蓝紫渐变、半透明、强调色到处都是。
- 字号飘忽、图标不齐、正文太小，按最终尺寸看不清。
- 一屏塞了太多同等重要的内容，没有主次。
- 动效很忙但没有目的：漂浮、乱弹、逐字蹦出、全站 250ms。

## 不做什么

- 从零做品牌、视觉方向或全新页面。
- 只改文案、只做翻译或只写提示语。
- 后端、数据或功能 bug。
- 只做安全/无障碍审计；这些可以在视觉修复中顺带检查，但不是本 skill 的主任务。
- 没有具体页面/代码/截图可审查的纯理论讨论。

## 怎么用

把本目录作为 skill 加载，或直接把 `SKILL.md` 交给支持 skill 的 agent。然后给一个具体目标：

```text
审查 ./landing，目标视口 1440×900。
这页像 AI 模板，帮我删掉重复文案和装饰卡片，
统一字号与颜色，把动效改得更有节奏。直接改代码。
```

有源码时，先跑候选扫描：

```bash
python3 scripts/audit_visual_code.py ./landing --format markdown
```

扫描器只找候选信号，不替代渲染检查。完整流程、修改约束和输出格式见 `SKILL.md`。

## 六遍审查

顺序固定：**文案 → 容器 → 颜色 → 字号与对齐 → 焦点 → 动效**。

1. 同一件事只说一次；删装饰英文、复述副标题、重复 CTA。
2. 先删装饰框；只有分组、层级、交互或状态才保留边界。
3. 先分配 canvas / text / muted / accent / state 角色，再谈渐变和透明。
4. 主要字号收敛到 3–4 档，用字重、间距、明度拉层次。
5. 一屏/一镜只讲一件事；删、降、排、聚、留。
6. 每个动作都要引导、揭示、展示变化、维持连续或提供反馈；至少分四档时长。

细则见：

- `references/six-pass-rubric.md`
- `references/motion-direction.md`

## 交付什么

1. 按严重度排序的问题表（最多 10 条，带文件:行或截图位置）。
2. 实际应用的最小代码修改。
3. 在目标视口下的验证结果；没有浏览器/截图时明确写“视觉验证未完成”。
4. 剩余风险，不伪造截图、数据或结论。

## 包内文件

- `SKILL.md`：触发面、工作流、修改规则、验证与输出契约。
- `references/six-pass-rubric.md`：六遍审查的判断规则、例子、严重度和网页/视频差异。
- `references/motion-direction.md`：动效目的、节拍、时长、缓动、镜头、反模式和检查清单。
- `scripts/audit_visual_code.py`：标准库静态扫描器，输出 Markdown/JSON 候选问题。
- `evals/`：触发边界与语义配置。
- `agents/interface.yaml`：接口元数据。
- `manifest.json`：本地生命周期元数据。
- `reports/`：yao-meta-skill 生成的本地审查与证据报告；可能含本机路径，默认不纳入 Git。

## 本地验证

```bash
python3 scripts/audit_visual_code.py <fixture> --format markdown
python3 scripts/audit_visual_code.py <fixture> --format json
python3 scripts/audit_visual_code.py <fixture> --fail-on high
```

扫描器退出码：`0` 正常；`2` 参数/目标错误，或 `--fail-on` 命中指定严重度。默认不因发现问题而失败。

完整包检查（需要 PyYAML）：

```bash
python3 /path/to/yao-meta-skill/scripts/yao.py validate .
```

触发评测：

```bash
python3 /path/to/yao-meta-skill/scripts/trigger_eval.py \
  --description-file SKILL.md \
  --cases evals/trigger_cases.json \
  --semantic-config evals/semantic_config.json

python3 /path/to/yao-meta-skill/scripts/trigger_eval.py \
  --description-file SKILL.md \
  --cases evals/holdout/trigger_cases.json \
  --semantic-config evals/semantic_config.json
```

`evals/holdout` 是建包时一起写的内部回归集，不是独立盲评证据；详见 `evals/README.md`。

## 边界

- 本包只存在于当前工作区，未做任何全局安装。
- 不新增依赖、字体、图标库或远程资源，除非用户同意。
- 不删除事实、法律文字、表单 label、导航、alt/ARIA 名称或交互入口。
- 删除有风险时先降级：移出首屏、缩小、改成次要文字或折叠。
- 无法运行/截图时，交付静态修复并标注未完成的视觉验证。

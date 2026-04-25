---
name: video-shot-analysis-feishu
description: "视频拉片到飞书多维表格：当用户上传视频并要求拉片、拆镜头、分析分镜、复盘爆款视频、倒推生成分镜提示词或视频生成提示词，并把结果写入飞书表格/Base 时使用。基于 ffmpeg 抽镜头截图，基于 lark-cli 写入飞书 Base。"
---

# 视频拉片到飞书 Base

把用户上传的视频拆成镜头级记录，分析每个镜头的画面、时长、叙事作用、景别、运镜、声音/字幕，并倒推出可复刻的「生成分镜提示词」和「生成视频提示词」，最后写入飞书多维表格。

## 必用依赖

- 先按任务读取 `lark-shared` 与 `lark-base` skill；如果用户明确要求普通电子表格，再读取 `lark-sheets`。
- 使用本 skill 的 `scripts/extract_shots.py` 先抽镜头段和代表截图。
- 用 `lark-cli base +...` 操作多维表格；附件截图必须用 `+record-upload-attachment` 上传，不能手写附件 token。

## 输入判断

最少需要：

- 本地视频路径，或用户上传的视频文件。
- 飞书目标：Base 链接/token + 表名/table-id；如果用户没有给目标，只问这一项。

如果用户只说“建一个表”，默认创建名为 `视频拉片分析` 的 Base 表。截图里的结构属于 Base，不默认用普通 Sheets。

## 推荐字段

字段顺序按截图习惯设计，新增了倒推提示词字段：

```json
[
  {"name":"镜头序号","type":"number","style":{"type":"plain","precision":0}},
  {"name":"镜头截图","type":"attachment"},
  {"name":"起止时间码","type":"text"},
  {"name":"时长","type":"number","style":{"type":"plain","precision":2}},
  {"name":"概述","type":"text"},
  {"name":"叙事作用","type":"text"},
  {"name":"景别","type":"select","multiple":false,"options":[
    {"name":"远景","hue":"Gray","lightness":"Lighter"},
    {"name":"全景","hue":"Blue","lightness":"Lighter"},
    {"name":"中景","hue":"Blue","lightness":"Light"},
    {"name":"中近景","hue":"Orange","lightness":"Lighter"},
    {"name":"近景","hue":"Orange","lightness":"Light"},
    {"name":"特写","hue":"Wathet","lightness":"Lighter"},
    {"name":"大特写","hue":"Purple","lightness":"Lighter"},
    {"name":"屏幕录制","hue":"Green","lightness":"Lighter"},
    {"name":"混合","hue":"Gray","lightness":"Light"}
  ]},
  {"name":"画面元素","type":"text"},
  {"name":"镜头运动","type":"text"},
  {"name":"转场/剪辑","type":"text"},
  {"name":"字幕/台词","type":"text"},
  {"name":"声音/音乐","type":"text"},
  {"name":"情绪/节奏","type":"text"},
  {"name":"视觉风格","type":"text"},
  {"name":"倒推生成分镜提示词","type":"text"},
  {"name":"倒推生成视频提示词","type":"text"},
  {"name":"备注/置信度","type":"text"}
]
```

创建字段前必须先 `+field-list` 查看现有字段，缺什么补什么，避免重复建字段。

## 工作流

1. **准备素材**
   - 确认视频路径存在。
   - 运行：
     ```bash
     python3 ~/.config/opencode/skills/video-shot-analysis-feishu/scripts/extract_shots.py \
       "/path/to/video.mp4" \
       --out-dir "./lapian_output" \
       --threshold 0.32 \
       --min-gap 0.45
     ```
   - 输出包括 `shots.json`、`shots.csv`、`frames/*.jpg`、`analysis_prompt.md`。

2. **镜头分析**
   - 逐张查看代表截图；短视频要尽量逐镜头分析，不要只粗略概括。
   - 如果同一镜头内信息变化大，必要时回看该片段或补抽帧。
   - 记录每个镜头：发生了什么、为什么放在这里、怎么引导观众、可复刻的镜头语言。

3. **倒推提示词**
   - `倒推生成分镜提示词`：写给图片/分镜生成模型，关注静态画面、构图、人物/界面、景别、光线、文字。
   - `倒推生成视频提示词`：写给视频生成模型，必须包含时间轴、镜头运动、动作、声音/台词、转场和结尾停帧。
   - 如果画面含中文 UI/字幕，提示词里明确“所有可见文字使用简体中文，禁止英文界面词”。

4. **写入 Base**
   - 先读取真实结构：
     ```bash
     lark-cli base +table-list --base-token <base_token>
     lark-cli base +field-list --base-token <base_token> --table-id <table_id>
     ```
   - 缺字段时按上面的 schema 用 `+field-create` 串行创建。
   - 对每个镜头先 `+record-upsert` 写非附件字段，拿到 `record_id`。
   - 再上传截图：
     ```bash
     lark-cli base +record-upload-attachment \
       --base-token <base_token> \
       --table-id <table_id> \
       --record-id <record_id> \
       --field-id "镜头截图" \
       --file "./lapian_output/frames/shot_001.jpg"
     ```

5. **校验**
   - 上传后抽查 `+record-list --limit 3`，确认文本字段和附件都存在。
   - 汇报总镜头数、写入成功数、附件成功数、失败项和飞书链接。

## 分析口径

- `概述`：只写画面事实和主要动作，不写长篇评论。
- `叙事作用`：解释这个镜头在注意力、信息推进、情绪、信任、卖点展示、转场中的作用。
- `景别`：从远景/全景/中景/中近景/近景/特写/大特写/屏幕录制/混合中选一个。
- `镜头运动`：固定、推近、拉远、横移、跟拍、环绕、摇镜、快速切换、屏幕滚动等。
- `转场/剪辑`：硬切、跳切、闪白、叠化、缩放转场、字幕承接、动作承接、音频承接。
- `声音/音乐`：口播、BGM、环境音、音效、停顿、重音；听不清就标注“未识别”。

## 长视频策略

- 3 分钟以内：逐镜头完整分析。
- 3-20 分钟：先自动切镜头，再按段落合并明显重复的屏录/口播镜头，但保留关键转折点。
- 超过 20 分钟：先输出章节级结构，让用户确认是否继续做逐镜头 Base。

## 失败处理

- ffmpeg 场景检测结果过碎：提高 `--threshold` 到 `0.42` 或提高 `--min-gap`。
- 场景检测漏切：降低 `--threshold` 到 `0.22`，或用 `--fallback-interval 1.5` 补采样。
- 截图超过 20MB 附件限制：脚本默认缩到 720px 宽；仍超限就用 `--width 480` 重跑。
- Base 链接是 `/wiki/`：先用 wiki 节点解析真实 `obj_token`，再作为 `--base-token`。

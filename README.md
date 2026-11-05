# Biboo

Biboo 帮英语老师用一份教学材料准备课堂 PPT 和跟读作业，再把需要人工判断的跟读交给老师复核。复核结果可以带进下一节课的备课。

项目保存在私有 GitHub 仓库，后续完成并验证的更新会继续同步。[GitHub 仓库](https://github.com/buu206/biboo)

仓库右侧 About 的 Website 指向本机 Demo。请在运行 Biboo 的这台 Mac 上打开，服务需要保持启动。[打开 Biboo Demo](http://127.0.0.1:18766/)

## 手动操作 Demo

在 Biboo 产品目录运行 `backend/.venv/bin/python scripts/demo.py`。第一次运行或更新依赖后，先执行下方的依赖安装命令。老师用邀请码 `biboo-demo` 登录。[打开本机 Demo](http://127.0.0.1:18766/)

老师端以侧栏切换备课、孩子跟读和复核。备课页将上传材料、核对目标、下载和发布分区呈现，孩子端集中展示当前练习与试听、录音操作。视觉方向按已确认的 MagicSchool、Edu.ai 设计稿和 Astrid 组合实现。

复核页将自动评测与老师的最终判定并排显示，手机端上下呈现。[Edu.ai 设计参考](https://dribbble.com/shots/27746307-Edu-ai-AI-Co-Teacher-for-K-12-lesson-planning)

### 1. 老师备课并发布

1. 进入「老师备课」，点「用示例材料试一试」，也可以上传一份虚构教案、讲义或旧课件。支持 PPTX、DOCX、可选中文字的 PDF、TXT 和 Markdown，单份限 10 MB。
2. 如果想直接看上传材料排成课件的效果，点「仅生成 PPT」，再点「下载 PPTX」。课件可在 PowerPoint 中编辑，长材料会展示节选。扫描版 PDF 需要先转成可选中文字的 PDF。
3. 点「带入备课」，检查并修改建议的主题、词汇、句型或发音重点。选中「Biboo 体验班」，点「生成课件大纲与跟读作业」，编辑课堂活动与跟读题并保存。点「下载本课 PPT」导出基于这些目标和活动的课件，再点「确认发布并生成音频」。可以用已发布的「练习 th」单独测试跟读。

### 2. 家长协助孩子跟读

1. 在老师端点「打开孩子跟读」，也可以点「复制跟读链接」后在同一台电脑另开窗口。进入孩子端，选择刚发布的作业。
2. 选题并试听示范。点「模拟读得好」「模拟需要加练」或「模拟录音不清」，再点「提交跟读」。点「换一个测试学员」可以独立测试另一种结果。需要加练时按页面提示再次提交，最多两轮。录音不清或多次失败的练习会转给老师。也可以用成人录音测试录制或上传。

### 3. 老师复核并准备下一课

1. 切到「老师复核」，选择体验班和刚测试的作业，查看学员状态和共性问题。在「待老师复核」中试听原录音，选择老师判定，填写反馈或录制语音点评，点「保存复核」。再回到孩子端查看反馈。
2. 选择「建议继续巩固」时可填写加练重点，例如 `th`。有下节课建议后，点「带入下节课备课」，修改带入的目标并生成下一课的作业草稿。

Demo 使用本机模板生成作业，以预设结果模拟口语评测。原题和加练示范用 macOS 的 Samantha 美式英语音色慢速朗读。Demo 无需云服务凭证，数据保存在 `data/manual-demo/`。请使用虚构教材、测试学员名和成人录音。

产品范围按飞书 PRD 的老师备课、孩子跟读、老师复核三段核对。孩子端在本机 Demo 使用网页，沿用项目状态中的 Web 端决定。[飞书 PRD](https://my.feishu.cn/wiki/R6BlwHeXIi8aMskuPHHcG2uTnPc?from=from_copylink) · [本地 PRD 快照](docs/PRD/PRD.md)

## 本机启动

在此目录打开终端。第一次使用时执行：

```bash
python3.12 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt
```

先用模拟模式体验流程。在产品目录创建试用老师，再启动服务：

```bash
BIBOO_DATA_DIR=../data/demo backend/.venv/bin/python scripts/create_teacher.py "试用老师"
cd backend
BIBOO_FAKE_MODELS=1 BIBOO_DATA_DIR=../data/demo .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

终端会显示一次邀请码。打开 [Biboo 验收页](http://127.0.0.1:8000) 并输入该邀请码。每次生成邀请码都会创建独立的老师账号。若 8000 端口已被占用，可把启动命令和浏览器地址里的端口同时换成 18765。

模拟作业单独存放在 `data/demo/`，音频为测试提示音。真实环境默认用 `data/`，首次启动时自动运行数据库迁移。后台 API 说明在 [本机接口文档](http://127.0.0.1:8000/docs)。

## 真实凭证和验证

1. 打开 `backend/.env`。如果文件还未创建，先从 `backend/.env.example` 复制一份。设置 `TTS_PROVIDER=aihubmix` 和 `BIBOO_FAKE_MODELS=0`，填写 `DEEPSEEK_API_KEY` 与 `AIHUBMIX_API_KEY`。凭证保存在本机文件中。
2. 从产品目录运行 `backend/.venv/bin/python scripts/smoke.py`。脚本使用临时数据库和虚构教学目标，经 DeepSeek 生成五份评分样例，再用所选语音服务发布其中一份并检查每段音频。真实调用按用量计费。记录与样例写入 `docs/evidence/阶段2-1/`。
3. 要在页面使用真实模型，先在产品目录运行 `backend/.venv/bin/python scripts/create_teacher.py "试用老师"` 创建真实数据目录的账号，再从 `backend/` 运行 `.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`。AIHubMix 验收只使用虚构练习文字，课堂样例须去掉姓名等个人信息。
4. 从工具包根目录运行 `bash kit.sh 自检 Biboo`，或直接运行 `bash verify.sh Biboo 阶段2-1`。

AIHubMix 的默认模型为 `gpt-4o-mini-tts`，音色为 `coral`。`AIHUBMIX_TTS_MODEL` 和 `AIHUBMIX_TTS_VOICE` 可配置。使用腾讯云语音合成时，将 `TTS_PROVIDER` 设为 `tencent` 并填写 `TENCENTCLOUD_SECRET_ID` 与 `TENCENTCLOUD_SECRET_KEY`。阶段 2-2 的发音评测凭证按该阶段方案准备。

## 阶段 2-2 跟读验收

阶段 2-2 的真实评测、阈值校准与阶段闸门单独验收。手动 Demo 的预设结果只用于验证操作和分流，真实冒烟仍待验。

登录后选一份已发布作业，在「跟读评测」中选题、试听示范、录音或上传 WAV，再提交跟读。模拟模式可以检查三类反馈与两轮加练的流程。真实验收请使用已同意参与的成人录音。

在本机 `backend/.env` 中填写 `TENCENT_SOE_APP_ID`、`TENCENTCLOUD_SECRET_ID` 和 `TENCENTCLOUD_SECRET_KEY`，保留 `DEEPSEEK_API_KEY`，并设 `BIBOO_FAKE_MODELS=0`。凭证说明见腾讯云新版口语评测文档。[腾讯云快速入门](https://cloud.tencent.com/document/product/1774/107347)

真实冒烟从产品目录运行 `backend/.venv/bin/python scripts/smoke_practice.py`，带 `--adult-consent` 和 5–10 个 `--case 类型=路径.wav` 参数，覆盖 `clean`、`wrong`、`noisy`。录音文本为 `think`，格式为 16 kHz 单声道 16 位 PCM WAV。结果和评分样例会写入 `docs/evidence/阶段2-2/`。

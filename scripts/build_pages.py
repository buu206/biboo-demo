"""Build the public static demo, without copying backend data or credentials."""
from pathlib import Path
import re, shutil
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'public-demo'
OUT.mkdir(exist_ok=True)
s=(ROOT/'backend/static/index.html').read_text()
s=s.replace('<script>', '<script src="./demo.js"></script>\n<script>',1)
s=s.replace('<body>', '<body>\n<aside class="public-demo-banner" role="note">免费演示 · AI 结果使用示例数据 · 操作仅保存在此浏览器，不上传材料或录音</aside>')
s=s.replace('</style>', '''.public-demo-banner {position:relative;z-index:60;padding:10px 18px;text-align:center;background:#f1ecfa;color:#675281;font-size:13px;line-height:1.6;}
#practice-record,#practice-stop,#practice-file,#practice-upload .file-alternative label,#practice-preview {display:none!important;}
#practice-upload .record-hint {display:none;}
#courseware-purpose-hint {color:#765780;}
#practice-upload .file-alternative {text-align:center;}
#practice-samples .actions {justify-content:center;}
</style>''',1)
s=s.replace("function viewUrl(view, lessonId) {", "function viewUrl(view, lessonId) { return BibooDemo.share(view, lessonId); }\nfunction unusedOriginalViewUrl(view, lessonId) {")
s=s.replace("return Boolean(navigator.mediaDevices?.getUserMedia && window.MediaRecorder);", "return false; // Public demo never requests microphone access.")
s=s.replace("async function startRecording(onAudio, onError, onEnded) {", "async function startRecording(onAudio, onError, onEnded) { throw new Error('公开演示使用预设结果，不采集录音。'); }\nasync function unusedOriginalRecording(onAudio, onError, onEnded) {")
a=s.index('function setPracticeAudioSource(');b=s.index('function renderPractice()',a)
s=s[:a]+'''function setPracticeAudioSource(audio, source) { audio.dataset.demoSource = source || ''; }
const practiceAudioError = '浏览器朗读暂时不可用，可以先看文字或换浏览器。';
async function playPracticeExample(audio) {
  try { BibooDemo.speak(audio.id === 'practice-drill-example' ? $('practice-drill-text').textContent : $('practice-reference').textContent); }
  catch(error) { practiceStatus(error.message,true); }
}
'''+s[b:]
s=s.replace("const audio = add(row, 'audio'); audio.controls = true; audio.preload = 'none';\n      audio.setAttribute('aria-label', '试听 ' + item.text);\n      audio.src = practiceMockMode ? '/api/v1/practice/items/' + item.id + '/demo-audio' : '/api/v1/assets/' + item.audio_asset_id;", "const listen = add(row, 'button', '听 ' + item.text); listen.className='secondary'; listen.onclick=()=>{ try {BibooDemo.speak(item.text);} catch(error){status(error.message,true);} };")
s=s.replace('本机演示链接需在这台电脑、同一演示账号中打开。','分享链接包含演示题目，别人也能打开；双方的练习记录互不共享。')
s=s.replace('演示模式。可用预设录音测试跟读结果，示范使用本机英文语音。','免费公开演示。示范使用浏览器朗读，反馈为预设结果，不做真实口语评分。')
s=s.replace('发布会生成示范语音并锁定题目；你可以先修改内容。','发布会锁定演示题目；朗读由浏览器提供，不调用付费模型。')
s=s.replace('复制跟读链接','复制演示链接')
s=s.replace('每次练习','每次练习')
s=s.replace('<details class="file-alternative">','<details class="file-alternative" open>')
s=s.replace('家长 / 老师帮忙','选择一种演示结果')
s=s.replace('本机验收请用成人录音；每段最长 30 秒，最大 2 MB。','无需麦克风。选一种示例，再点「提交跟读」查看模拟反馈。')
s=s.replace('体验不同的练习反馈 · 模拟录音','模拟结果，不是真实发音评分')
s=s.replace('选择 WAV 文件','公开演示不上传音频')
s=s.replace('当前不', '当前不')
# No voice uploads in teacher review either.
s=s.replace("const fileUpload = file.files[0];", "const fileUpload = null;")
s=s.replace("file.accept = '.wav,audio/wav,audio/x-wav';", "file.accept = '.wav,audio/wav,audio/x-wav'; file.closest('label').hidden = true;")
s=s.replace("if (!practiceMockMode && !confirm('发布当前作业并生成示范语音？发布后题目将锁定。')) return;", "if (!confirm('确认发布这份演示作业？仅保存在当前浏览器，题目将锁定。')) return;")
s=s.replace("function pptTeachingSummary(response) {", "function pptTeachingSummary(response) {return '免费版下载的是预制海洋主题样例，不根据本次材料生成；含点击动画与示范音。';}\nfunction unusedTeachingSummary(response) {")
s=s.replace("function coursewareFilename(response, title) {", "function coursewareFilename(response, title) {return 'Biboo-海洋课堂-演示样例.pptx';}\nfunction unusedCoursewareFilename(response, title) {")
s=s.replace("$('courseware-generate').textContent = homework ? '准备跟读作业' : (selectedCoursewareStyle() === 'children' ? '生成儿童互动 PPT' : '生成文字 PPT');", "$('courseware-generate').textContent = homework ? '准备演示作业' : '获取示例 PPT';")
s=s.replace("$('courseware-purpose-hint').textContent = homework ? '提取词汇和句型，确认后生成作业。发布前你还可以修改。' : (selectedCoursewareStyle() === 'children' ? '默认适合 6–10 岁，含分步动画和单词示范音。' : '按统一版式整理材料文字。');", "$('courseware-purpose-hint').textContent = homework ? 'TXT / Markdown 在浏览器整理词汇；其他格式使用海洋示例。材料不会上传。' : '免费版提供预制海洋主题 PPT，可体验分步动画与声音，不根据上传材料生成。';")
s=s.replace('默认适合 6–10 岁，含分步动画和单词示范音。','免费版下载预制海洋主题 PPT；上传材料不影响样例内容。')
s=s.replace('生成儿童互动 PPT','获取示例 PPT')
s=s.replace("ppt.textContent = selectedCoursewareStyle() === 'children' ? '下载儿童互动 PPT' : '下载文字 PPT';", "ppt.textContent = '下载示例 PPT';")
s=s.replace("$('lesson-ppt-style-field').hidden = !lesson?.outline;", "$('lesson-ppt-style-field').hidden = true;")
s=s.replace('<select id="courseware-style"', '<select disabled id="courseware-style"')
s=s.replace("$('logout').onclick = () => perform(async () => {", "$('logout').textContent='重置体验';\n$('logout').onclick = () => {if(confirm('清除这个浏览器里的演示课程和练习记录？'))BibooDemo.reset();};\nconst unusedOriginalLogout = () => perform(async () => {")
s=s.replace('真实模式会生成教学文案和单词语音；教学提示在备注里。','公开演示下载固定样例；完整模型功能见 GitHub 仓库。')
s=s.replace("return '作业已发布。可以复制链接，或先体验孩子端。';", "return '演示作业已发布。可复制链接给别人体验，记录分别保存在各自浏览器。';")
s=s.replace("return '跟读结果已更新。';", "return '模拟反馈已更新；这不代表真实发音水平。';")
(OUT/'index.html').write_text(s)
shutil.copy2(ROOT/'web/demo/demo.js',OUT/'demo.js')
shutil.copytree(ROOT/'web/demo/assets',OUT/'assets',dirs_exist_ok=True)
(OUT/'.nojekyll').touch()
print('Built public-demo; no backend, credentials or runtime data copied.')

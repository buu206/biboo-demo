/* Public, browser-only sandbox. Never connects to Biboo's real backend. */
(() => {
  'use strict';
  const key = 'biboo-public-demo-v1';
  const nativeFetch = window.fetch.bind(window);
  const root = new URL('./', location.href);
  const clone = value => JSON.parse(JSON.stringify(value));
  const words = ['octopus', 'crab', 'turtle'];
  const meaning = {octopus:'章鱼',crab:'螃蟹',turtle:'海龟',football:'足球',basketball:'篮球',apple:'苹果',banana:'香蕉'};
  function createLesson(input, id) {
    const vocabulary = (Array.isArray(input.vocabulary) ? input.vocabulary : words).slice(0,8).map(w=>String(w).slice(0,60));
    return {id, class_id:Number(input.class_id)||1, topic:String(input.topic||'海洋朋友 · 示例课').slice(0,140), age_band:String(input.age_band||'6–10 岁').slice(0,50), duration_minutes:Number(input.duration_minutes)||25, vocabulary, patterns:[], sound_focus:[], status:'draft', revision:1, quality_notes:['免费演示：内容由本地模板整理，不调用 AI。'], outline:null, items:[]};
  }
  function generate(lesson) {
    lesson.outline={sections:[{title:'热身 · 猜一猜',minutes:5,activity:'展示动物图片，邀请孩子说出认识的朋友。'},{title:'听一听 · 说一说',minutes:10,activity:'围绕本课词汇听示范，再轮流跟读。'},{title:'课堂小游戏',minutes:7,activity:'同桌轮流描述或做动作，另一位猜单词。'},{title:'回顾与作业',minutes:3,activity:'回顾今天的词汇，再发布跟读作业。'}]};
    lesson.items=lesson.vocabulary.map((text,i)=>({id:lesson.id*100+i+1,kind:'word',text,translation:meaning[text.toLowerCase()]||'（示例词汇，请老师核对）',speaker:null,audio_asset_id:null}));
    lesson.status='generated';lesson.revision++;return lesson;
  }
  function seed() {
    const lesson=generate(createLesson({vocabulary:words},1));lesson.status='published';
    return {version:1,classes:[{id:1,name:'示例英语班'}],lessons:[lesson],attempts:[],sequence:2};
  }
  let state;
  try {state=JSON.parse(localStorage.getItem(key));} catch {}
  if (!state || state.version!==1 || !Array.isArray(state.lessons) || !Array.isArray(state.attempts) || !Array.isArray(state.classes)) state=seed();
  function save() {localStorage.setItem(key,JSON.stringify(state));}
  function readSharedLesson(value) {
    try {
      if(!value || value.length>16000) return null;
      const obj=JSON.parse(decodeURIComponent(escape(atob(value))));
      if(!Number.isSafeInteger(obj.id)||obj.id<1||obj.id>1e12||!Array.isArray(obj.items)||obj.items.length<1||obj.items.length>8) return null;
      const lesson=generate(createLesson({topic:obj.topic,vocabulary:obj.items.map(i=>String(i.text).slice(0,60))},obj.id));
      lesson.items.forEach((i,n)=>{i.translation=String(obj.items[n].translation||'').slice(0,140);});
      lesson.status='published';return lesson;
    } catch { return null; }
  }
  const shared=readSharedLesson(new URL(location.href).searchParams.get('demo'));
  if(shared){state.lessons=state.lessons.filter(l=>l.id!==shared.id);state.lessons.push(shared);save();}
  function share(view,id) {
    const url=new URL(root);if(view!=='teacher')url.searchParams.set('view',view);
    if(id)url.searchParams.set('lesson',id);
    const l=state.lessons.find(l=>String(l.id)===String(id));
    if(l?.status==='published') url.searchParams.set('demo',btoa(unescape(encodeURIComponent(JSON.stringify({id:l.id,topic:l.topic,items:l.items.map(i=>({text:i.text,translation:i.translation}))})))));
    return url.href;
  }
  function speak(text) {
    if(!('speechSynthesis' in window))throw Error('此浏览器不支持朗读，可查看文字示范或换用 Chrome / Safari。');
    speechSynthesis.cancel();const voice=new SpeechSynthesisUtterance(text);voice.lang='en-US';voice.rate=.8;speechSynthesis.speak(voice);
  }
  function item(id) {for(const l of state.lessons){const i=l.items.find(i=>i.id===Number(id));if(i)return {lesson:l,item:i};}return null;}
  function reply(data,status=200,headers={}) {return new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json',...headers}});}
  function fail(message,status=400){return reply({error:{code:'DEMO_ONLY',message}},status);}
  function dashboard(classId,lessonId) {
    const lessons=state.lessons.filter(l=>l.class_id===classId&&l.status==='published'&&(!lessonId||l.id===Number(lessonId)));
    const ids=new Set(lessons.flatMap(l=>l.items.map(i=>i.id)));
    const attempts=state.attempts.filter(a=>ids.has(a.item_id));
    const learners=[...new Set(attempts.map(a=>a.learner_id))];
    const students=learners.map((id,n)=>{const mine=attempts.filter(a=>a.learner_id===id);const completed=new Set(mine.filter(a=>a.decision==='good'||a.teacher_feedback).map(a=>a.item_id)).size;return {label:'体验学员 '+(n+1),completed_items:completed,total_items:ids.size,status:completed===ids.size?'completed':mine.some(a=>a.decision==='teacher_review'&&!a.teacher_feedback)?'pending_review':'in_progress'};});
    const details=a=>({...a,learner_label:'体验学员 '+(learners.indexOf(a.learner_id)+1),lesson_title:item(a.item_id)?.lesson.topic,review:a.teacher_feedback,audio_url:null});
    const queue=attempts.filter(a=>a.decision==='teacher_review'&&!a.teacher_feedback).map(details);
    const recent=attempts.filter(a=>a.teacher_feedback).map(details);
    return {class_id:classId,counts:{learners:learners.length,completed:students.filter(s=>s.status==='completed').length,pending_review:queue.length,reviewed:recent.length,attempts:attempts.length},students,queue,recent_reviews:recent,common_issues:[],suggestion:attempts.length?{topic:'再和海洋朋友打个招呼',vocabulary:words,patterns:[],sound_focus:[],reason:'示例建议：回顾课堂词汇，给每位孩子一次开口机会。'}:null,reminder:'示例提醒：今天一起听一听、读一读课堂里的词汇吧。'};
  }
  window.BibooDemo={share,speak,readSharedLesson,reset(){localStorage.removeItem(key);location.href=root.href;}};
  window.fetch=async(input,options={})=>{
    const url=new URL(typeof input==='string'?input:input.url,location.href);
    if(url.origin!==location.origin) return fail('公开演示不连接外部服务。');
    if(!url.pathname.startsWith('/api/v1/')) return nativeFetch(input,options);
    const path=url.pathname.slice(7),method=options.method||'GET';
    const body=typeof options.body==='string'?JSON.parse(options.body):{};
    try {
      if(path==='/health') return reply({status:'ok',mode:'mock'});
      if(path==='/auth/me'||path==='/auth/login')return reply({id:1,name:'体验老师'});
      if(path==='/auth/logout')return reply({ok:true});
      if(path==='/classes'){
        if(method==='POST'){if(state.classes.length>=20)return fail('演示班级已达上限，可以重置体验。');const c={id:state.classes.length+1,name:String(body.name||'示例班级').slice(0,140)};state.classes.push(c);save();return reply(c);}
        return reply(state.classes);
      }
      if(path==='/lessons'){
        if(method==='POST'){if(state.lessons.length>=30)return fail('演示课程已达上限，可以重置体验。');const l=createLesson(body,Date.now()%1e12);state.lessons.push(l);save();return reply(l);}
        return reply(state.lessons.filter(l=>!url.searchParams.get('class_id')||String(l.class_id)===url.searchParams.get('class_id')));
      }
      const lessonMatch=path.match(/^\/lessons\/(\d+)(?:\/(generate|content|publish))?$/);
      if(lessonMatch){const l=state.lessons.find(l=>l.id===Number(lessonMatch[1]));if(!l)return fail('这份演示作业不在当前浏览器中，请使用包含课程的分享链接。',404);
        const action=lessonMatch[2];
        if(method!=='GET'&&l.status==='published')return fail('已发布的示例题目已锁定。');
        if(action==='generate'&&method==='POST')generate(l);
        if(action==='content'&&method==='PUT'){l.outline={sections:body.outline};for(const i of body.items||[]){const old=l.items.find(a=>a.id===i.id);if(old){old.text=String(i.text).slice(0,140);old.translation=String(i.translation).slice(0,140);}}l.revision++;}
        if(action==='publish'&&method==='POST'){if(!body.confirm)return fail('请先确认发布。');l.status='published';l.revision++;}
        save();return reply(l);
      }
      if(path==='/courseware/goals'){
        const filename=url.searchParams.get('filename')||'';
        const isText=/\.(txt|md)$/i.test(filename);
        const source=isText&&options.body?.size<=100000?await options.body.text():'';
        const tokens=[...new Set((source.match(/[a-zA-Z][a-zA-Z'-]{1,25}/g)||[]).map(s=>s.toLowerCase()))].filter(w=>!['the','and','for','this','that','with','are','can'].includes(w)).slice(0,8);
        return reply({topic:url.searchParams.get('title')||filename.replace(/\.[^.]+$/,'')||'示例课堂',vocabulary:tokens.length?tokens:words,patterns:[],sound_focus:[],warnings:['免费演示仅在浏览器整理 TXT / Markdown；其他材料使用海洋主题示例，不会上传文件。']});
      }
      if(/^\/courseware\/pptx(?:\/\d+)?$/.test(path)){
        const r=await nativeFetch(new URL('assets/biboo-sample.pptx',root));if(!r.ok)return fail('示例课件暂时未能下载，请刷新重试。',503);
        return new Response(await r.blob(),{headers:{'Content-Type':'application/vnd.openxmlformats-officedocument.presentationml.presentation','Content-Disposition':"attachment; filename=biboo-demo-sample.pptx",'X-Slide-Count':'15','X-Courseware-Planner':'demo'}});
      }
      const practice=path.match(/^\/practice\/items\/(\d+)\/attempts$/);
      if(practice){const found=item(practice[1]);if(!found)return fail('请选择示例题目。',404);
        const learner=url.searchParams.get('learner_id');const mine=state.attempts.filter(a=>a.item_id===found.item.id&&a.learner_id===learner);
        if(method==='GET')return reply(mine);
        const requestKey=new Headers(options.headers).get('Idempotency-Key');const existing=state.attempts.find(a=>a.key===requestKey&&a.learner_id===learner);if(existing)return reply(existing);
        if(['good','teacher_review'].includes(mine.at(-1)?.decision))return fail('这题已完成，请进入下一题。');
        const bytes=await options.body.arrayBuffer();const data=new DataView(bytes);let peak=0;for(let i=44;i+1<bytes.byteLength;i+=2)peak=Math.max(peak,Math.abs(data.getInt16(i,true)));
        const decision=mine.length>=2||peak<100?'teacher_review':peak>6000?'practice':'good';
        const a={id:state.sequence++,key:requestKey,item_id:found.item.id,learner_id:learner,round:mine.length,reference:found.item.text,decision,feedback:decision==='good'?'示例反馈：读得很清楚，继续保持！':decision==='practice'?'示例反馈：听一遍示范，再慢慢读一次。':'示例反馈：这次请老师来听一听。',reason:'预设结果演示，不是真实发音评分。',drill:decision==='practice'?{text:found.item.text}:null,teacher_feedback:null,audio_url:null};
        if(state.attempts.length>=300)return fail('演示记录已达上限，可以重置体验。');state.attempts.push(a);save();return reply(a);
      }
      const review=path.match(/^\/review\/classes\/(\d+)\/dashboard$/);if(review)return reply(dashboard(Number(review[1]),url.searchParams.get('lesson_id')));
      const feedback=path.match(/^\/review\/attempts\/(\d+)$/);if(feedback&&method==='PUT'){const a=state.attempts.find(a=>a.id===Number(feedback[1]));if(!a)return fail('找不到这条演示记录。',404);a.teacher_feedback={verdict:body.verdict==='good'?'good':'practice',note:String(body.note||'').slice(0,600),focus:String(body.focus||'').slice(0,60),audio_url:null};save();return reply(a.teacher_feedback);}
      if(path.endsWith('/feedback-audio'))return fail('公开演示只保存文字点评，不上传录音。');
      return fail('此功能需要完整后端；公开版仅演示流程。',404);
    }catch(error){return fail(error.name==='QuotaExceededError'?'浏览器存储已满，请重置体验。':'演示数据处理失败，请重置体验后再试。');}
  };
})();

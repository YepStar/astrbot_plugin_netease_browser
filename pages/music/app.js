(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let state, labels, busy=false, commentOffset=0, editDraft=null, clearScope=null;
  const el=(tag,text,cls)=>{const n=document.createElement(tag);n.textContent=text||'';if(cls)n.className=cls;return n;};
  const msg=(text,error=false)=>{$('message').textContent=text;$('message').classList.toggle('error',error);};
  async function api(method,path,body){
    const sdk=window.AstrBotPluginPage;
    if(!sdk)throw Error('请从 AstrBot 插件页面打开音乐面板');
    const out=method==='GET'?await sdk.apiGet(path,body||{}):await sdk.apiPost(path,body||{});
    if(out?.error||out?.status==='error')throw Error(out.error||out.message||'请求失败');
    return out;
  }
  function fields(){
    const cfg=state.settings;
    const groups={
      'identity-fields':['api_base','owner_umo','owner_uid','persona_id','provider_id'],
      'basic-fields':['enabled','browse_enabled','share_enabled','together_enabled','auto_accept','comments_enabled','qq_notice','room_control_enabled'],
      'memory-fields':['memory_read_enabled','memory_plugin'],
      'auto-fields':['autonomous_enabled','autonomous_share','autonomous_invite','autonomous_comment','autonomous_room_control'],
      'limit-fields':['start_hour','end_hour','decision_gap_minutes','daily_listen_limit','daily_outreach_limit','outreach_gap_minutes','invite_ttl_minutes','poll_seconds','max_listen_seconds','offer_ttl_minutes','join_reminder_seconds','room_action_gap_seconds','room_session_minutes']};
    for(const [id,keys] of Object.entries(groups)){
      $(id).replaceChildren();
      for(const key of keys){
        const bool=typeof cfg[key]==='boolean', label=el('label',null,bool?'toggle':'field');
        label.append(el('span',labels[key]));
        const input=document.createElement(key==='memory_plugin'?'select':'input');input.id='cfg-'+key;input.dataset.key=key;
        if(key==='memory_plugin'){
          const plugins=state.memory_plugins||[];
          for(const plugin of plugins){const option=el('option',plugin.id+(plugin.supported?(plugin.active?'':'（未启用）'):'（不支持读取接口）'));option.value=plugin.id;option.disabled=!plugin.supported||!plugin.active;input.append(option);}
          if(!plugins.some(plugin=>plugin.id===cfg[key])){const option=el('option',cfg[key]+'（当前未加载）');option.value=cfg[key];input.append(option);}
          input.value=cfg[key];label.append(input);$(id).append(label);continue;
        }
        input.type=bool?'checkbox':typeof cfg[key]==='number'?'number':'text';
        if(bool)input.checked=cfg[key];else input.value=cfg[key];
        if(key==='owner_uid')input.placeholder='你的网易云数字 UID（留空不发送）';
        if(key==='persona_id')input.placeholder='用于自主选曲的人格 ID';
        label.append(input);$(id).append(label);
      }
    }
  }
  const sourceStatus={ok:'正常',disabled:'已关闭',unavailable:'不可用',unsupported:'不支持读取接口',denied:'未获会话读取授权',persona_mismatch:'人格不匹配',invalid_response:'接口返回无效'};
  const statuses={switch_deferred:'暂不切歌，等待用户再次要求',pending:'进行中',sent:'已发送',unknown:'结果不确定',failed:'失败',completed:'播放完成',partial:'部分播放',interrupted:'播放中断',accepted:'已加入',posted:'已发表',applied:'已执行',declined:'已拒绝'};
  function render(){
    const song=state.playback||state.room?.song;
    $('account').textContent=state.account?.nickname|| (state.configured?'已保存登录，请验证':'尚未登录');
    $('binding').textContent=state.settings.owner_uid?'接收用户 UID · '+state.settings.owner_uid:'收件人未绑定';
    $('now').textContent=song?'《'+song.name+'》':'暂无播放';
    $('progress').textContent=state.playback?'已解码 '+Math.floor(state.playback.played_seconds)+' 秒':state.room?.room_id?'一起听房间 '+state.room.room_id:'实时播放状态';
    $('together-status').textContent=state.together_offer?'已在 QQ 提议一起听《'+state.together_offer.song.name+'》，等待你的回答。尚未发送网易云邀请。':state.room?.room_id?(state.room.joined?'已进入同一房间，可以一起听、切歌和暂停。':'已发出网易云原生一起听邀请，等待你进入房间。'):'';
    const preferences=state.music_preferences||{items:[],status:{}};
    $('preference-status').textContent='QQ 对话：'+(sourceStatus[preferences.status.dialogue]||'尚未筛选')+' · 记忆：'+(sourceStatus[preferences.status.memory]||'尚未读取')+' · 筛选：'+(sourceStatus[preferences.status.extraction]||'尚未执行')+(preferences.updated_at?' · 更新于 '+new Date(preferences.updated_at*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}):'');
    $('preference-items').replaceChildren();
    for(const row of [...preferences.items].reverse()){
      const entry=el('article',null,'entry'), head=el('div',null,'entry-head');
      head.append(el('b',row.kind==='manual'?'手动音乐建议':row.kind==='dialogue'?'QQ 音乐建议':'记忆 · '+row.plugin));
      const edit=el('button','编辑','secondary edit-advice');edit.type='button';edit.setAttribute('aria-label','编辑建议：'+row.quote.slice(0,40));
      edit.onclick=()=>{
        editDraft={mode:"edit",entry_id:row.entry_id,revision:row.revision,scope:preferences.scope};
        $("preference-editor-title").textContent="编辑音乐建议";$("preference-edit-save").textContent="保存修改";
        $('preference-edit-quote').value=row.quote;
        $('preference-edit-context').value=(row.context_quotes||[]).map(source=>source.quote).join('\n');
        $('preference-edit-error').textContent='';$('preference-editor').showModal();
      };
      const remove=el('button','删除','danger delete-advice');remove.type='button';remove.setAttribute('aria-label','删除建议：'+row.quote.slice(0,40));
      remove.onclick=()=>action(async()=>{await api('POST','preferences/delete',{entry_id:row.entry_id,revision:row.revision,scope:preferences.scope});await load();msg('已删除这条音乐建议。');});
      const buttons=el('div',null,'entry-actions');buttons.append(edit,remove);head.append(buttons);entry.append(head,el('p',row.quote),...((row.context_quotes||[]).map(source=>el('p','关联说明：'+source.quote,'hint'))),el('small',(row.kind==='manual'?(row.edited_at?'手动新增 · 已修改 · ':'手动新增 · '):row.manual?'已手动编辑 · ':'')+new Date((row.edited_at||row.recorded_at)*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})+(row.kind==='manual'?'':' · 原始来源 '+(row.source_id||row.id))));
      $('preference-items').append(entry);
    }
    if(!preferences.items.length)$('preference-items').append(el('p','尚无音乐建议。可点击“新增建议”，或从 QQ 对话与已授权的记忆中筛选。','hint'));
    $('autonomy').textContent=state.autonomy||'暂无活动';
    $('room').textContent=state.room?.room_id?JSON.stringify(state.room,null,2):'未连接一起听房间';
    $('observations').replaceChildren();
    for(const r of state.observations){const n=el('article',null,'entry');n.append(el('b',r.song?.name||r.song_id),el('p',r.note||statuses[r.status]||r.status),el('small',new Date(r.at*1000).toLocaleString('zh-CN')+' · '+Math.floor(r.played_seconds||0)+' 秒'));$('observations').append(n);}
    if(!state.observations.length)$('observations').append(el('p','还没有播放记录。','hint'));
    $('receipts').replaceChildren();
    for(const r of state.recent){const n=el('article',null,'entry');n.append(el('b',({share:'歌曲分享',invite:'一起听邀请',listen:'歌曲播放',accept:'接受邀请',comment:'公开评论',together_proposal:'QQ一起听提议',together_reply:'一起听确认',join_reminder:'入房提醒',room_control:'房间播放控制'}[r.kind]||r.kind)+' · '+(statuses[r.status]||r.status)),el('p','歌曲 / 房间 '+(r.song_id||r.room_id||'—')),el('small',new Date(r.at*1000).toLocaleString('zh-CN')));$('receipts').append(n);}
    if(!state.recent.length)$('receipts').append(el('p','尚无执行回执。','hint'));
  }
  async function loadComments(offset=0){
    const data=await api('GET','comments',{offset});commentOffset=data.offset;
    $('comment-rows').replaceChildren();
    for(const record of data.items){
      const row=el('tr'),songCell=el('td'),song=record.song;
      const title=song?.name||('歌曲 ID '+record.song_id);
      if(/^\d+$/.test(record.song_id||'')){const link=el('a',title);link.href='https://music.163.com/#/song?id='+record.song_id;link.target='_blank';link.rel='noopener noreferrer';songCell.append(link);}else songCell.append(el('b',title));
      if(song?.artists)songCell.append(el('small',song.artists));
      const time=Number(record.posted_at||record.at);
      const timeCell=el('td',Number.isFinite(time)?new Date(time*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}):'时间未记录');
      const body=el('td');if(record.reply_id)body.append(el('small','回复评论 · '+record.reply_id));
      body.append(el('p',typeof record.content==='string'?record.content:'旧版本未记录评论正文'));
      row.append(songCell,timeCell,body);$('comment-rows').append(row);
    }
    $('comment-count').textContent='共 '+data.total+' 条'+(data.total?' · 当前 '+(data.offset+1)+'—'+(data.offset+data.items.length)+' 条':'');
    $('comment-empty').hidden=data.total!==0;
    $('comment-prev').hidden=data.offset===0;$('comment-next').hidden=data.offset+data.limit>=data.total;
  }
  async function load(fill=false){state=await api('GET','status');if(fill)fields();render();}
  async function action(fn){if(busy)return;busy=true;for(const b of document.querySelectorAll('button'))b.disabled=true;try{await fn();}catch(e){msg(e.message||'操作失败',true);}finally{busy=false;for(const b of document.querySelectorAll('button'))b.disabled=false;}}
  for(const b of document.querySelectorAll('[data-tab]'))b.onclick=()=>{for(const n of document.querySelectorAll('[data-tab]'))n.setAttribute('aria-selected',String(n===b));for(const t of document.querySelectorAll('.tab'))t.hidden=t.id!==b.dataset.tab;if(b.dataset.tab==='comments')action(()=>loadComments());};
  $('preferences-refresh').onclick=()=>action(async()=>{await api('POST','preferences/refresh');await load();msg('已更新音乐建议，可在此查看来源和筛选状态。');});
  $('preferences-add').onclick=()=>{
    editDraft={mode:'add',scope:state.music_preferences.scope};
    $('preference-editor-title').textContent='新增音乐建议';$('preference-edit-save').textContent='新增建议';
    $('preference-edit-quote').value='';$('preference-edit-context').value='';$('preference-edit-error').textContent='';$('preference-editor').showModal();
  };
  $('preference-edit-cancel').onclick=()=>$('preference-editor').close();
  $('preference-editor').onclose=()=>{editDraft=null;};
  $('preference-edit-form').onsubmit=e=>{
    e.preventDefault();if(!editDraft)return;
    const {mode,...identity}=editDraft;
    const update={...identity,quote:$('preference-edit-quote').value.trim(),context:$('preference-edit-context').value.trim()};
    action(async()=>{try{await api('POST',mode==='add'?'preferences/add':'preferences/edit',update);$('preference-editor').close();await load();msg(mode==='add'?'已新增音乐建议，后续选歌会参考这条内容。':'这条音乐建议已保存，后续选歌会使用修改后的内容。');}catch(error){$('preference-edit-error').textContent=error.message||'保存失败，请重试。';throw error;}});
  };
  $('preferences-clear').onclick=()=>{clearScope=state.music_preferences.scope;$('preferences-clear-error').textContent='';$('preferences-clear-confirm').showModal();};
  $('preferences-clear-cancel').onclick=()=>$('preferences-clear-confirm').close();
  $('preferences-clear-confirm').onclose=()=>{clearScope=null;};
  $('preferences-clear-submit').onclick=()=>{
    if(!clearScope)return;const scope=clearScope;
    action(async()=>{try{await api('POST','preferences/clear',{confirmed:true,scope});$('preferences-clear-confirm').close();await load();msg('已清空当前会话的音乐建议。');}catch(error){$('preferences-clear-error').textContent=error.message||'清空失败，请重试。';throw error;}});
  };
  $('comment-prev').onclick=()=>action(()=>loadComments(Math.max(0,commentOffset-50)));
  $('comment-next').onclick=()=>action(()=>loadComments(commentOffset+50));
  $('refresh').onclick=()=>action(async()=>{await load();if(!$('comments').hidden)await loadComments();msg('已刷新状态，表单中未保存的设置仍保留。');});
  $('settings-form').onsubmit=e=>{e.preventDefault();action(async()=>{const cfg={};for(const input of document.querySelectorAll('[data-key]'))cfg[input.dataset.key]=input.type==='checkbox'?input.checked:input.type==='number'?Number(input.value):input.value.trim();await api('POST','settings',cfg);await load(true);msg('设置已保存到本地，后续操作立即使用新设置。');});};
  $('qr').onclick=()=>action(async()=>{const r=await api('POST','login/qr');if(!r.image.startsWith('data:image/'))throw Error('二维码无效');$('qr-image').src=r.image;$('qr-image').hidden=false;msg(r.message);});
  $('check').onclick=()=>action(async()=>{const r=await api('POST','login/check');msg(r.message);if(r.code===803){$('qr-image').hidden=true;await load();}});
  $('account-check').onclick=()=>action(async()=>{await api('POST','account/check');await load();msg('当前网易云登录有效。');});
  $('stop').onclick=()=>action(async()=>{await api('POST','stop');await load();msg('已停止当前音乐活动。');});
  (async()=>{try{await window.AstrBotPluginPage.ready();labels={"memory_read_enabled":"允许读取记忆", "memory_plugin":"记忆插件","enabled": "启用网易云插件", "api_base": "网易云 API 服务地址", "owner_umo": "绑定 QQ 私聊 UMO", "owner_uid": "接收分享/邀请的网易云 UID", "persona_id": "自主听歌人格 ID", "provider_id": "自主决策模型 Provider ID（留空跟随会话）", "browse_enabled": "允许 bot 搜索与浏览歌曲", "share_enabled": "网易云站内歌曲分享", "together_enabled": "一起听房间与邀请", "auto_accept": "自动接受绑定用户的一起听邀请", "notify_song_change": "一起听换歌时 QQ 告知", "comments_enabled": "允许网易云公开评论/回复", "autonomous_enabled": "人设与陪伴状态驱动的自主听歌", "autonomous_share": "自主听歌后可私信分享", "autonomous_invite": "自主听歌后可邀请用户一起听", "autonomous_comment": "自主听歌后可发表公开评论", "qq_notice": "允许 QQ 主动消息（确认与人格表达）", "start_hour": "每日活动开始小时（北京时间）", "end_hour": "每日活动结束小时（北京时间）", "decision_gap_minutes": "自主决策间隔（分钟）", "daily_listen_limit": "每天最多自主听歌次数", "daily_outreach_limit": "每天最多主动分享/邀请次数", "outreach_gap_minutes": "主动分享/邀请间隔（分钟）", "invite_ttl_minutes": "邀请房间保留时间（分钟）", "poll_seconds": "房间状态轮询间隔（秒）", "max_listen_seconds": "单首最多播放秒数", "offer_ttl_minutes": "QQ 提议有效时间（分钟）", "join_reminder_seconds": "接受后未入房提醒等待（秒）", "room_control_enabled": "允许一起听切歌、暂停和继续", "autonomous_room_control": "同房时允许 bot 自主切歌或暂停", "room_action_gap_seconds": "房间自主决策最短间隔（秒）", "room_session_minutes": "同房活动最长时间（分钟）"};await load(true);msg('音乐面板已连接。');}catch(e){msg(e.message||'连接失败，请重新打开插件页面。',true);}})();
})();

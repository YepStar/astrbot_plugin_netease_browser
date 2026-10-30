(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let state, labels, busy=false, commentOffset=0;
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
      'auto-fields':['autonomous_enabled','autonomous_share','autonomous_invite','autonomous_comment','autonomous_room_control'],
      'limit-fields':['start_hour','end_hour','decision_gap_minutes','daily_listen_limit','daily_outreach_limit','outreach_gap_minutes','invite_ttl_minutes','poll_seconds','max_listen_seconds','offer_ttl_minutes','join_reminder_seconds','room_action_gap_seconds','room_session_minutes']};
    for(const [id,keys] of Object.entries(groups)){
      $(id).replaceChildren();
      for(const key of keys){
        const bool=typeof cfg[key]==='boolean', label=el('label',null,bool?'toggle':'field');
        label.append(el('span',labels[key]));
        const input=document.createElement('input');input.id='cfg-'+key;input.dataset.key=key;
        input.type=bool?'checkbox':typeof cfg[key]==='number'?'number':'text';
        if(bool)input.checked=cfg[key];else input.value=cfg[key];
        if(key==='owner_uid')input.placeholder='你的网易云数字 UID（留空不发送）';
        if(key==='persona_id')input.placeholder='用于自主选曲的人格 ID';
        label.append(input);$(id).append(label);
      }
    }
  }
  const statuses={pending:'进行中',sent:'已发送',unknown:'结果不确定',failed:'失败',completed:'播放完成',partial:'部分播放',interrupted:'播放中断',accepted:'已加入',posted:'已发表',applied:'已执行',declined:'已拒绝'};
  function render(){
    const song=state.playback||state.room?.song;
    $('account').textContent=state.account?.nickname|| (state.configured?'已保存登录，请验证':'尚未登录');
    $('binding').textContent=state.settings.owner_uid?'接收用户 UID · '+state.settings.owner_uid:'收件人未绑定';
    $('now').textContent=song?'《'+song.name+'》':'暂无播放';
    $('progress').textContent=state.playback?'已解码 '+Math.floor(state.playback.played_seconds)+' 秒':state.room?.room_id?'一起听房间 '+state.room.room_id:'实时播放状态';
    $('together-status').textContent=state.together_offer?'已在 QQ 提议一起听《'+state.together_offer.song.name+'》，等待你的回答。尚未发送网易云邀请。':state.room?.room_id?(state.room.joined?'已进入同一房间，可以一起听、切歌和暂停。':'邀请已发送到网易云私信，等待你进入房间。'):'';
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
  $('comment-prev').onclick=()=>action(()=>loadComments(Math.max(0,commentOffset-50)));
  $('comment-next').onclick=()=>action(()=>loadComments(commentOffset+50));
  $('refresh').onclick=()=>action(async()=>{await load();if(!$('comments').hidden)await loadComments();msg('已刷新状态，表单中未保存的设置仍保留。');});
  $('settings-form').onsubmit=e=>{e.preventDefault();action(async()=>{const cfg={};for(const input of document.querySelectorAll('[data-key]'))cfg[input.dataset.key]=input.type==='checkbox'?input.checked:input.type==='number'?Number(input.value):input.value.trim();await api('POST','settings',cfg);await load(true);msg('设置已保存到本地，后续操作立即使用新设置。');});};
  $('qr').onclick=()=>action(async()=>{const r=await api('POST','login/qr');if(!r.image.startsWith('data:image/'))throw Error('二维码无效');$('qr-image').src=r.image;$('qr-image').hidden=false;msg(r.message);});
  $('check').onclick=()=>action(async()=>{const r=await api('POST','login/check');msg(r.message);if(r.code===803){$('qr-image').hidden=true;await load();}});
  $('account-check').onclick=()=>action(async()=>{await api('POST','account/check');await load();msg('当前网易云登录有效。');});
  $('stop').onclick=()=>action(async()=>{await api('POST','stop');await load();msg('已停止当前音乐活动。');});
  (async()=>{try{await window.AstrBotPluginPage.ready();labels={"enabled": "启用网易云插件", "api_base": "网易云 API 服务地址", "owner_umo": "绑定 QQ 私聊 UMO", "owner_uid": "接收分享/邀请的网易云 UID", "persona_id": "自主听歌人格 ID", "provider_id": "自主决策模型 Provider ID（留空跟随会话）", "browse_enabled": "允许 bot 搜索与浏览歌曲", "share_enabled": "网易云站内歌曲分享", "together_enabled": "一起听房间与邀请", "auto_accept": "自动接受绑定用户的一起听邀请", "notify_song_change": "一起听换歌时 QQ 告知", "comments_enabled": "允许网易云公开评论/回复", "autonomous_enabled": "人设与陪伴状态驱动的自主听歌", "autonomous_share": "自主听歌后可私信分享", "autonomous_invite": "自主听歌后可邀请用户一起听", "autonomous_comment": "自主听歌后可发表公开评论", "qq_notice": "允许 QQ 主动消息（确认与人格表达）", "start_hour": "每日活动开始小时（北京时间）", "end_hour": "每日活动结束小时（北京时间）", "decision_gap_minutes": "自主决策间隔（分钟）", "daily_listen_limit": "每天最多自主听歌次数", "daily_outreach_limit": "每天最多主动分享/邀请次数", "outreach_gap_minutes": "主动分享/邀请间隔（分钟）", "invite_ttl_minutes": "邀请房间保留时间（分钟）", "poll_seconds": "房间状态轮询间隔（秒）", "max_listen_seconds": "单首最多播放秒数", "offer_ttl_minutes": "QQ 提议有效时间（分钟）", "join_reminder_seconds": "接受后未入房提醒等待（秒）", "room_control_enabled": "允许一起听切歌、暂停和继续", "autonomous_room_control": "同房时允许 bot 自主切歌或暂停", "room_action_gap_seconds": "房间自主决策最短间隔（秒）", "room_session_minutes": "同房活动最长时间（分钟）"};await load(true);msg('音乐面板已连接。');}catch(e){msg(e.message||'连接失败，请重新打开插件页面。',true);}})();
})();

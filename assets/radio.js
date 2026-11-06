/* 小鲸电台 · HTML 番组播放器
 *
 * 对齐 myradio 的核心机制：
 *   - 页面只有台本 JSON + 音频 MP3，播放位置驱动字幕 / 话题 / 角色。
 *   - 台本把 say（朗读）与 show（字幕）分开，字幕显示正确表记。
 *   - 口型由 Web Audio 的实时音量驱动，不预设阈值，换声音也能对上。
 * 交互契约对齐官方 index.html：
 *   - 跳转只改 currentTime，不改变播放 / 暂停状态（"reads like an article"）。
 *   - 要点手风琴，一次只展开一个；分段切换时收起当前分段的要点。
 *   - 大标题点击复制文字，跳转交给编号 / 章节 / 台本句子。
 *   - 角色不跟随鼠标、不响应点击；只按段落语境切换动作 / 表情，配合呼吸与口型。
 * 画面：1600×900 虚拟舞台，按容器等比缩放成 16:9，整屏即可录成视频。
 * 本项目的差异：主播是真 Live2D Cubism 4 模型，而非差分静态图。
 */
(function () {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const MODEL_URL = 'assets/model/大肥鱼.model3.json';
  const GLITCH_PARTS = ['Part10', 'Part46'];
  const SPEEDS = [1, 1.25, 1.5, 0.75];

  const audio = $('audio');
  let episode = null, lines = [], topics = [], duration = 0;
  let currentLine = -1, currentTopic = -1, speedIndex = 0;
  let model = null, pixiApp = null, modelW = 0, modelH = 0;
  let audioCtx = null, analyser = null, timeBuf = null;
  let db = -60, ref = -60, mouth = 0, audioReady = false;
  const MOTION_COUNT = 7;   // model3.json 里 TapBody 组的动作数量

  // ---------- 工具 ----------
  function fmt(sec) {
    sec = Math.max(0, sec || 0);
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return m + ':' + String(s).padStart(2, '0');
  }

  async function loadJSON(url) {
    const r = await fetch(url, { cache: 'no-store' });
    if (!r.ok) throw new Error(url + ' → HTTP ' + r.status);
    return r.json();
  }

  function hostOf(url) {
    try { return new URL(url).hostname.replace(/^www\./, ''); } catch (e) { return '—'; }
  }

  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

  // 官方是 1920×1080 虚拟舞台等比缩放；这里用 1600×900，录屏天然 16:9
  function fitStage() {
    const frame = $('frame');
    if (frame) frame.style.setProperty('--scale', String(frame.clientWidth / 1600));
  }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }

  // ---------- 数据 ----------
  async function loadEpisode() {
    const list = await loadJSON('episodes.json');
    if (!list.length) throw new Error('episodes.json 里没有期数');
    const entry = list[0];
    episode = await loadJSON(entry.file);
    audio.src = entry.audio;
    topics = episode.topics || [];
    lines = [];
    topics.forEach((t, ti) => (t.lines || []).forEach((l, li) => {
      lines.push({ say: l.say, show: l.show, start: l.start, end: l.end, topic: ti, li: li });
    }));
    duration = episode.duration || (lines.length ? lines[lines.length - 1].end : 0);
    $('totTime').textContent = fmt(duration);
    $('seek').max = duration;
    $('dateLabel').innerHTML = episode.date.replace(/-/g, '.') + '<br>NO.001';
    document.title = episode.title + ' · 小鲸电台';
    $('transcriptMeta').textContent = topics.length + ' 段 ／ ' + lines.length + ' 句 ／ ' + fmt(duration);
    const c = episode.credits || {};
    $('creditsLine').innerHTML = '<b>台本</b> ' + (c.script || 'DeepSeek') +
      ' ／ <b>主播</b> ' + (c.caster || 'DeepSeek-chan Live2D') +
      ' ／ <b>语音</b> ' + (c.voice || 'macOS 本地合成');
    buildChapters();
    buildTranscript();
    buildNews();
    buildMarks();
    setupMediaSession();
    restorePosition();
  }

  function buildChapters() {
    const box = $('chapters');
    box.innerHTML = '';
    topics.forEach((t, i) => {
      const b = document.createElement('button');
      b.className = 'chap';
      b.dataset.i = i;
      b.innerHTML = t.id + '<em>' + fmt(t.start) + '</em>';
      b.title = t.title + ' · ' + fmt(t.start) + '（跳到这里）';
      // 官方契约：跳转只移动播放位置，不改变播放/暂停状态
      b.addEventListener('click', () => seekTo(t.start + 0.02));
      box.appendChild(b);
    });
  }

  function buildMarks() {
    const box = $('marks');
    box.innerHTML = '';
    topics.slice(1).forEach((t) => {
      const i = document.createElement('i');
      i.style.left = (t.start / duration * 100) + '%';
      box.appendChild(i);
    });
  }

  function buildTranscript() {
    const body = $('transcriptBody');
    body.innerHTML = '';
    topics.forEach((t, ti) => {
      const g = document.createElement('div');
      g.className = 't-group';
      const h = document.createElement('h3');
      h.innerHTML = '<span>' + t.id + ' / ' + fmt(t.start) + '</span>' + t.title;
      g.appendChild(h);
      (t.lines || []).forEach((l, li) => {
        const b = document.createElement('button');
        b.className = 't-line';
        b.dataset.key = ti + ':' + li;
        b.innerHTML = '<i>' + fmt(l.start) + '</i>' + l.show;
        b.addEventListener('click', () => seekTo(l.start + 0.02));
        g.appendChild(b);
      });
      body.appendChild(g);
    });
    $('transcriptToggle').addEventListener('click', () => $('transcript').classList.toggle('open'));
  }

  // ---------- 本期新闻阅读区（对齐 myradio 的 news[].points / details / link） ----------
  const PIC_COLORS = [
    ['#1D3B8C', '#3D5AFE'], ['#0F6E8C', '#31B0C8'], ['#4A3A8C', '#7A5AF8'],
    ['#8C3A4A', '#D9646E'], ['#1D6B52', '#3DBE8B'],
  ];

  function picFallback(node, topic, pal) {
    node.innerHTML = '<span class="pn">' + esc(topic.id) + '</span><span class="ps">' +
      esc(topic.kicker) + '</span>';
    node.style.background = 'linear-gradient(135deg,' + pal[0] + ',' + pal[1] + ')';
  }

  function copyPlain(text) {
    const legacy = () => {
      const ta = document.createElement('textarea');
      ta.value = text; ta.style.cssText = 'position:fixed;opacity:0';
      document.body.appendChild(ta); ta.select();
      let ok = false;
      try { ok = document.execCommand('copy'); } catch (e) {}
      ta.remove();
      return ok;
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text).then(() => true).catch(legacy);
    }
    return Promise.resolve(legacy());
  }

  function copyText(text, btn, ok) {
    copyPlain(text).then((done) => {
      if (!done) return;
      const old = btn.textContent;
      btn.textContent = ok;
      setTimeout(() => { btn.textContent = old; }, 1400);
    });
  }

  // 对齐官方 showDetail()：一次只展开一个要点；切换话题时全部收起
  function closeAllDetails(selector) {
    document.querySelectorAll(selector || '.news-point, .fact-btn').forEach((b) => {
      b.setAttribute('aria-expanded', 'false');
      const d = b.nextElementSibling;
      if (d && (d.classList.contains('news-detail') || d.classList.contains('fact-detail'))) {
        d.classList.remove('open');
      }
    });
  }

  function toggleDetail(btn, det) {
    const willOpen = !det.classList.contains('open');
    closeAllDetails();
    if (willOpen) {
      det.classList.add('open');
      btn.setAttribute('aria-expanded', 'true');
    }
  }

  function buildNews() {
    const box = $('newsList');
    box.innerHTML = '';
    const news = [];
    topics.forEach((t, i) => { if (t.points && t.points.length) news.push({ t: t, i: i }); });
    $('newsMeta').textContent = news.length + ' 条 ／ 点要点展开详情';

    news.forEach(({ t, i }, order) => {
      const link = t.link || {};
      const pal = PIC_COLORS[order % PIC_COLORS.length];
      const art = document.createElement('article');
      art.className = 'news-item';
      art.dataset.topic = i;
      art.innerHTML =
        '<div class="news-top">' +
          '<button class="news-num" title="跳到这条新闻">' + esc(t.id) + '</button>' +
          '<button class="news-title" title="点标题复制文字">' +
            '<b>' + esc(t.title) + '</b>' +
            '<small class="news-sub">' + esc(t.kicker) + ' · ' + fmt(t.start) + ' · ' +
              (t.lines || []).length + ' 句</small>' +
          '</button>' +
          '<span class="news-badge">● 正在播报</span>' +
        '</div>' +
        '<div class="news-body"><div>' +
          '<ul class="news-points"></ul><div class="news-sources"></div>' +
        '</div><div class="news-pic"></div></div>';

      // 要点：点击就地展开对应 details（官方的交互核心）
      const ul = art.querySelector('.news-points');
      t.points.forEach((p, pi) => {
        const li = document.createElement('li');
        const btn = document.createElement('button');
        btn.className = 'news-point';
        btn.setAttribute('aria-expanded', 'false');
        btn.innerHTML = '<i>▸</i><span>' + esc(p) + '</span>';
        const det = document.createElement('div');
        det.className = 'news-detail';
        det.textContent = (t.details && t.details[pi]) || '暂无更多细节。';
        btn.addEventListener('click', () => toggleDetail(btn, det));
        li.appendChild(btn); li.appendChild(det); ul.appendChild(li);
      });

      // 来源 / 复制 / 分享
      const src = art.querySelector('.news-sources');
      const a = document.createElement('a');
      a.href = link.url || t.url; a.target = '_blank'; a.rel = 'noopener';
      a.textContent = '来源 · ' + (link.site || hostOf(t.url)) + ' ↗';
      src.appendChild(a);

      const cpTitle = document.createElement('button');
      cpTitle.textContent = '复制标题';
      cpTitle.addEventListener('click', () => copyText(t.title, cpTitle, '已复制 ✓'));
      src.appendChild(cpTitle);

      const cpLink = document.createElement('button');
      cpLink.textContent = '复制本条链接';
      cpLink.addEventListener('click', () => copyText(
        location.origin + location.pathname + '?t=' + Math.floor(t.start), cpLink, '已复制 ✓'));
      src.appendChild(cpLink);

      // OGP 图：只热链、不落地；失败自动降级成本地图卡
      const pic = art.querySelector('.news-pic');
      picFallback(pic, t, pal);
      if (link.image) {
        const img = new Image();
        img.alt = ''; img.referrerPolicy = 'no-referrer';
        img.onload = () => { pic.innerHTML = ''; pic.style.background = '#EEF2FA'; pic.appendChild(img); };
        img.onerror = () => picFallback(pic, t, pal);
        img.src = link.image;
      }

      // 官方：大标题点击复制文字（便于搜索），跳转交给编号 / 章节
      const titleBtn = art.querySelector('.news-title');
      const sub = titleBtn.querySelector('.news-sub');
      const subText = sub.textContent;
      titleBtn.addEventListener('click', () => {
        copyPlain(t.title).then((ok) => {
          if (!ok) return;
          sub.textContent = '已复制 ✓  ' + subText;
          setTimeout(() => { sub.textContent = subText; }, 1400);
        });
      });
      art.querySelector('.news-num').addEventListener('click', () => seekTo(t.start + 0.02));
      box.appendChild(art);
    });
  }

  // ---------- 播放控制 ----------
  function play() {
    initAudioGraph();
    if (audioCtx && audioCtx.state === 'suspended') audioCtx.resume();
    audio.play().catch(() => {});
  }

  function togglePlay() { audio.paused ? play() : audio.pause(); }

  function seekTo(t) {
    try { audio.currentTime = Math.max(0, Math.min(duration - 0.05, t)); } catch (e) {}
    sync(true);
  }

  function jumpTopic(delta) {
    const now = audio.currentTime;
    let idx;
    if (delta > 0) {
      idx = topics.findIndex((t) => t.start > now + 0.3);
      if (idx < 0) idx = topics.length - 1;
    } else {
      // 当前话题开始 2 秒内则回退到上一个，否则回到本话题开头
      const cur = currentTopic;
      idx = (now - (topics[cur] ? topics[cur].start : 0) > 2) ? cur : Math.max(0, cur - 1);
    }
    seekTo(topics[idx].start + 0.02);
  }

  function setOnAir(on) {
    $('onair').classList.toggle('live', on);
    $('onair').querySelector('span').textContent = on ? 'ON AIR' : 'STANDBY';
    $('bigPlay').classList.toggle('hidden', on);   // 播放中隐藏视频式大播放按钮
    $('playIcon').innerHTML = on
      ? '<path d="M3.5 2.5h3.2v11H3.5zM9.3 2.5h3.2v11H9.3z"/>'
      : '<path d="M4 2.2v11.6L13.4 8 4 2.2z"/>';
  }

  $('shareNow').addEventListener('click', (e) => {
    const url = location.origin + location.pathname + '?t=' + Math.floor(audio.currentTime);
    copyText(url, e.currentTarget, '已复制 ✓');
  });

  $('play').addEventListener('click', togglePlay);
  audio.addEventListener('play', () => setOnAir(true));
  audio.addEventListener('pause', () => setOnAir(false));
  audio.addEventListener('ended', () => { setOnAir(false); localStorage.removeItem(storageKey()); });

  $('seek').addEventListener('input', (e) => { seekTo(parseFloat(e.target.value)); });
  $('speed').addEventListener('click', () => {
    speedIndex = (speedIndex + 1) % SPEEDS.length;
    const s = SPEEDS[speedIndex];
    audio.playbackRate = s;
    $('speed').textContent = (Number.isInteger(s) ? s.toFixed(1) : String(s)) + '×';
  });

  document.addEventListener('keydown', (e) => {
    if (e.target.tagName === 'INPUT') return;
    if (e.code === 'Space') { e.preventDefault(); togglePlay(); }
    if (e.code === 'ArrowRight') jumpTopic(1);
    if (e.code === 'ArrowLeft') jumpTopic(-1);
  });

  function storageKey() { return 'dsradio:' + (episode ? episode.date : '') + ':pos'; }
  let saveTick = 0;
  audio.addEventListener('timeupdate', () => {
    if (audio.currentTime > 3 && audio.currentTime < duration - 8 && ++saveTick % 4 === 0) {
      try { localStorage.setItem(storageKey(), String(audio.currentTime)); } catch (e) {}
    }
  });

  function restorePosition() {
    let saved = 0;
    try { saved = parseFloat(localStorage.getItem(storageKey()) || '0'); } catch (e) {}
    const fromHash = parseFloat(new URLSearchParams(location.search).get('t') || '0');
    const t = fromHash || saved;
    if (t > 3 && t < duration - 8) {
      $('resume').style.display = 'flex';
      $('resumeAt').textContent = fmt(t);
      $('resumeBtn').addEventListener('click', () => {
        seekTo(t); play(); $('resume').style.display = 'none';
      });
      // 官方的 "Start over"：从头开始，并清掉续播记录
      $('resumeDismiss').addEventListener('click', () => {
        seekTo(0);
        $('resume').style.display = 'none';
        try { localStorage.removeItem(storageKey()); } catch (e) {}
      });
    }
    if (fromHash) { seekTo(t); }
  }

  function setupMediaSession() {
    if (!('mediaSession' in navigator)) return;
    try {
      navigator.mediaSession.metadata = new MediaMetadata({
        title: episode.title,
        artist: 'DeepSeek-chan',
        album: '小鲸电台 · ' + episode.date,
        artwork: [{ src: new URL('assets/portrait/caster.png', location.href).href, sizes: '852x852', type: 'image/png' }],
      });
      navigator.mediaSession.setActionHandler('play', play);
      navigator.mediaSession.setActionHandler('pause', () => audio.pause());
      navigator.mediaSession.setActionHandler('nexttrack', () => jumpTopic(1));
      navigator.mediaSession.setActionHandler('previoustrack', () => jumpTopic(-1));
      navigator.mediaSession.setActionHandler('seekto', (d) => seekTo(d.seekTime));
    } catch (e) {}
  }

  // ---------- 播放位置 → 界面 ----------
  function findLine(t) {
    for (let i = 0; i < lines.length; i++) {
      if (t < lines[i].start) return Math.max(0, i - 1); // 句间停顿：保持刚念完的那一句
      if (t < lines[i].end) return i;
    }
    return lines.length - 1;
  }

  function sync(force) {
    if (!lines.length) return;
    const t = audio.currentTime;
    const li = findLine(t);
    const line = lines[li];
    const ti = line ? line.topic : 0;

    if (!$('seek').matches(':active')) $('seek').value = t;
    $('curTime').textContent = fmt(t);

    if (force || li !== currentLine) {
      const sub = $('subtitle');
      if (li !== currentLine) {
        sub.classList.add('flip');
        setTimeout(() => { sub.textContent = line.show; sub.classList.remove('flip'); }, 90);
      } else {
        sub.textContent = line.show;
      }
      document.querySelectorAll('.t-line').forEach((el) => el.classList.remove('active'));
      const key = ti + ':' + line.li;
      const active = document.querySelector('.t-line[data-key="' + key + '"]');
      if (active) active.classList.add('active');
      currentLine = li;
    }

    if (force || ti !== currentTopic) {
      const topic = topics[ti];
      $('counter').textContent = String(ti + 1).padStart(2, '0') + ' / ' + String(topics.length).padStart(2, '0');
      $('kicker').textContent = topic.kicker;
      $('topicTitle').textContent = topic.title;
      document.querySelectorAll('.chap').forEach((el, i) => el.classList.toggle('active', i === ti));
      // 播放到哪条新闻，原文卡片就换成哪条（对齐官方 showCard() 的行为）
      const card = $('linkCard');
      const link = topic.link || {};
      const thumb = $('linkThumb');
      thumb.innerHTML = '';
      if (topic.url) {
        card.classList.remove('disabled');
        $('linkTitle').textContent = link.title || topic.title;
        $('linkHost').textContent = link.site || hostOf(topic.url);
        $('linkDesc').textContent = link.description || (topic.facts && topic.facts[0]) || '';
        $('linkGo').href = topic.url;
        thumb.textContent = (link.site || hostOf(topic.url)).split('.')[0].slice(0, 2).toUpperCase();
        if (link.image) {
          const img = new Image();
          img.alt = ''; img.referrerPolicy = 'no-referrer';
          img.onload = () => { thumb.innerHTML = ''; thumb.appendChild(img); };
          img.src = link.image;
        }
      } else {
        card.classList.add('disabled');
        $('linkTitle').textContent = '本段为串场，无原文链接';
        $('linkHost').textContent = '—';
        $('linkDesc').textContent = '';
        $('linkGo').removeAttribute('href');
        thumb.textContent = 'DS';
      }
      card.classList.remove('enter');
      void card.offsetWidth;   // 重启动画
      card.classList.add('enter');

      // 下方新闻阅读区：当前播报的那条自动高亮
      document.querySelectorAll('.news-item').forEach((el) => {
        el.classList.toggle('active', Number(el.dataset.topic) === ti);
      });

      // 按语境换动作 / 表情；panel 换段淡入（官方 .enter）
      applyCaster(topic);
      const panel = $('panel');
      panel.classList.remove('panel-enter');
      void panel.offsetWidth;
      panel.classList.add('panel-enter');

      // 当前分段：短要点 + 点击展开详情（对齐官方 panel 的 li.more）
      closeAllDetails('.fact-btn');
      const hasPts = !!(topic.points && topic.points.length);
      $('facts').classList.remove('empty');
      $('factsLabel').textContent = hasPts
        ? 'KEY POINTS / 本段要点 · 点开看详情'
        : 'TODAY / 本期目录 · 点标题跳转';
      const fl = $('factsList');
      fl.innerHTML = '';
      if (hasPts) {
        topic.points.forEach((p, pi) => {
          const item = document.createElement('li');
          const btn = document.createElement('button');
          btn.className = 'fact-btn';
          btn.setAttribute('aria-expanded', 'false');
          btn.innerHTML = '<i>▸</i><span>' + esc(p) + '</span>';
          const det = document.createElement('div');
          det.className = 'fact-detail';
          det.textContent = (topic.details && topic.details[pi]) || '暂无更多细节。';
          btn.addEventListener('click', () => toggleDetail(btn, det));
          item.appendChild(btn); item.appendChild(det);
          fl.appendChild(item);
        });
      } else {
        // 开场 / 片尾：列出本期新闻目录，点标题跳到对应段落（官方 TODAY 幻灯片）
        topics.forEach((n) => {
          if (!n.points || !n.points.length) return;
          const item = document.createElement('li');
          const btn = document.createElement('button');
          btn.className = 'fact-btn';
          btn.setAttribute('aria-expanded', 'false');
          btn.innerHTML = '<i>' + esc(n.id) + '</i><span>' + esc(n.title) + '</span>';
          btn.addEventListener('click', () => seekTo(n.start + 0.02));
          item.appendChild(btn);
          fl.appendChild(item);
        });
      }

      currentTopic = ti;
    }
  }

  audio.addEventListener('timeupdate', () => sync(false));
  audio.addEventListener('seeked', () => sync(true));
  audio.addEventListener('loadedmetadata', () => sync(true));

  // ---------- Web Audio：实时音量 → 口型 ----------
  function initAudioGraph() {
    if (audioReady) return;
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;
      audioCtx = new Ctx();
      const src = audioCtx.createMediaElementSource(audio);
      analyser = audioCtx.createAnalyser();
      analyser.fftSize = 1024;
      analyser.smoothingTimeConstant = 0.2;
      src.connect(analyser);
      analyser.connect(audioCtx.destination);
      timeBuf = new Float32Array(analyser.fftSize);
      audioReady = true;
    } catch (e) {
      console.warn('[radio] Web Audio 不可用，改用时间轴模拟口型', e);
      audioReady = false;
    }
  }

  function voiceLevel() {
    if (!audioReady || audio.paused) return 0;
    analyser.getFloatTimeDomainData(timeBuf);
    let e = 0;
    for (let i = 0; i < timeBuf.length; i++) e += timeBuf[i] * timeBuf[i];
    const now = 10 * Math.log10(e / timeBuf.length + 1e-12);
    db += (now - db) * (now > db ? 0.6 : 0.3);   // 快起慢落
    ref = Math.max(db, ref - 0.05);                // 追踪这段声音的「大声」基准
    if (db < ref - 22) return 0;
    if (db < ref - 5) return 0.42;
    return 1;
  }

  function fallbackLevel(t) {
    // 没有 Web Audio 时，按当前句的进度做轻微开合，保证画面不呆板
    if (audio.paused) return 0;
    return 0.25 + 0.45 * Math.abs(Math.sin(t * 11.5)) * (0.6 + 0.4 * Math.sin(t * 3.1));
  }

  // ---------- Live2D ----------
  function hideGlitchParts() {
    if (!model) return;
    try {
      const cm = model.internalModel.coreModel;
      GLITCH_PARTS.forEach((id) => { try { cm.setPartOpacityById(id, 0); } catch (e) {} });
    } catch (e) {}
  }

  // ---------- 按段落语境切换动作 / 表情 ----------
  // 台本里每段的 expression（exp3 名）与 motion（TapBody 组索引）驱动，
  // 开场挥手、重点新闻竖食指、惊讶用圈圈眼、片尾收势，避免整期一个姿势。
  function setExpression(name) {
    if (!model) return;
    document.body.dataset.lastExpression = name || '';
    try {
      const em = model.internalModel.motionManager.expressionManager;
      if (em && typeof em.resetExpression === 'function') em.resetExpression();
      if (name) model.expression(name);
    } catch (e) {}
    hideGlitchParts();
  }

  function playMotion(index) {
    if (!model || typeof index !== 'number' || index < 0 || index >= MOTION_COUNT) return;
    document.body.dataset.lastMotion = String(index);
    try {
      const p = model.motion('TapBody', index, 2);
      // 动作是「切换型」的，播完回到 Idle 呼吸循环，避免僵在末帧
      if (p && typeof p.then === 'function') {
        p.then(() => { try { model.motion('Idle'); } catch (e) {} }).catch(() => {});
      }
    } catch (e) {}
  }

  function applyCaster(topic) {
    if (!model || !topic) return;
    setExpression(topic.expression);
    playMotion(topic.motion);
  }

  function layout() {
    if (!model || !pixiApp || !modelW || !modelH) return;
    const W = pixiApp.screen.width, H = pixiApp.screen.height;
    // 机位加高到 620 与左侧面板对齐后，保持角色绝对大小与头顶位置不变，
    // 让多出来的 80px 自然露出更多下半身（用户允许显示更多身体）。
    const sW = (W * 0.94) / modelW;
    const sH = (H * 1.50) / modelH;
    const s = Math.min(sW, sH);
    document.body.dataset.camGeom = W + 'x' + H + ' s=' + s.toFixed(4);
    model.scale.set(s);
    model.x = (W - modelW * s) / 2;
    model.y = -H * 0.14;
  }

  // 每帧只覆盖口型与轻微呼吸；眼睛 / 头部朝向完全交给 Idle 动作，不跟鼠标。
  // 必须写在模型 update 之后（LOW 优先级），否则会被 Idle 动作重置。
  function writeFrame(level) {
    if (!model) return;
    mouth += (level - mouth) * 0.38;
    const t = performance.now() / 1000;
    try {
      const cm = model.internalModel.coreModel;
      const set = (id, v) => { try { cm.setParameterValueById(id, v); } catch (e) {} };
      set('ParamMouthOpenY', clamp(mouth, 0, 1));
      set('ParamMouthForm', mouth * 0.35);
      set('ParamAngleZ', Math.sin(t * 0.55) * 1.2);
      set('ParamBodyAngleX', Math.sin(t * 0.8) * 0.8);
    } catch (e) {}
  }

  async function initLive2D() {
    const host = $('live2d');
    try {
      // 虚拟舞台尺寸固定（外层 #stage 整体 scale），PIXI 画布也固定 660×540。
      // 不能用 resizeTo：被 CSS transform 缩放过的容器尺寸读取不稳定，
      // 会让 model.scale 忽大忽小，录屏时角色构图漂移。
      pixiApp = new PIXI.Application({
        width: 660, height: 620,
        transparent: true, antialias: true, autoDensity: true,
        resolution: Math.min(window.devicePixelRatio || 1, 2),
        backgroundAlpha: 0,
      });
      host.appendChild(pixiApp.view);
      // 5 张贴图并发请求，偶发单张失败会让整个 from() reject；重试一次即可恢复
      let lastErr = null;
      for (let attempt = 0; attempt < 3 && !model; attempt++) {
        try {
          model = await PIXI.live2d.Live2DModel.from(MODEL_URL, { autoInteract: false });
        } catch (e) {
          lastErr = e;
          if (attempt < 2) await new Promise((r) => setTimeout(r, 400 * (attempt + 1)));
        }
      }
      if (!model) throw lastErr || new Error('Live2D 模型加载失败');
      pixiApp.stage.addChild(model);
      modelW = model.internalModel.width;
      modelH = model.internalModel.height;
      layout();
      hideGlitchParts();

      // LOW 优先级 = 模型 update 之后写入，避免被 idle 动作每帧重置
      // （与桌宠项目里 setOutfit 的写法一致，已验证有效）
      const level = () => audioReady ? voiceLevel() : fallbackLevel(audio.currentTime);
      try {
        pixiApp.ticker.add(() => writeFrame(level()), null, PIXI.UPDATE_PRIORITY.LOW);
      } catch (e) {
        pixiApp.ticker.add(() => writeFrame(level()));
      }
      try { model.motion('Idle'); } catch (e) {}
      // 模型是异步加载的，sync(true) 可能早已跑过；这里补一次当前段落的动作/表情
      if (currentTopic >= 0) applyCaster(topics[currentTopic]);
      document.body.dataset.l2d = 'ok';
      $('loading').classList.add('gone');
    } catch (e) {
      const msg = String((e && (e.stack || e.message)) || e).slice(0, 400);
      document.body.dataset.l2dError = msg;
      console.error('[radio] Live2D 加载失败，降级为静态立绘：' + msg);
      $('live2d').style.display = 'none';
      $('portraitFallback').style.display = 'flex';
      $('loading').classList.add('gone');
    }
  }

  // 视频式交互：点画面任意处播放 / 暂停；面板里的可点元素不触发切换
  $('bigPlay').addEventListener('click', (e) => { e.stopPropagation(); play(); });
  $('frame').addEventListener('click', (e) => {
    if (e.target.closest && e.target.closest('#bigPlay, button, a, input, .fact-detail')) return;
    togglePlay();
  });

  // 当前新闻的原文卡片：整卡可点（官方 a#card）
  $('linkCard').addEventListener('click', () => {
    const href = $('linkGo').getAttribute('href');
    if (href && href !== '#') window.open(href, '_blank', 'noopener');
  });
  $('linkGo').addEventListener('click', (e) => e.stopPropagation());

  // ---------- 启动 ----------
  (async function start() {
    if (location.protocol === 'file:') {
      $('loading').textContent = '请用本地 HTTP 服务打开（见终端输出）';
      return;
    }
    fitStage();
    window.addEventListener('resize', fitStage);
    try {
      await loadEpisode();
    } catch (e) {
      $('loading').textContent = '台本载入失败：' + e.message;
      console.error(e);
      return;
    }
    initLive2D();
    sync(true);
    setInterval(() => sync(false), 200);
    // 嵌入 / 调试场景：?autoplay=1 配合浏览器允许自动播放时使用
    if (new URLSearchParams(location.search).get('autoplay') === '1') play();
  })();
})();

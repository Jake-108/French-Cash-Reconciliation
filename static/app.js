const $ = id => document.getElementById(id);
let STATE = null;

function money(n){ return (Number(n)||0).toFixed(2); }

// A box may hold a number, be blank (nothing entered yet), or hold "-"
// meaning "we have no data for this site". "-" counts as filled and is
// treated as no data (numeric 0, and exempt from the gap check) downstream.
function isBlank(v){ return String(v).trim() === ''; }
function isNoData(v){ const s = String(v).trim(); return s === '-' || s === '–'; }
function cellNum(v){ if(isNoData(v)) return 0; const n = parseFloat(v); return isNaN(n) ? 0 : n; }

// Flag every active-row box that's still empty (a value or "-" clears it).
// Returns the list of offending inputs so callers can block and focus.
function flagIncomplete(){
  const boxes = ['.counted', '.sortie', '.depot'];
  const bad = [];
  $('grid').querySelectorAll('tbody tr').forEach(tr => {
    if(tr.classList.contains('dup')) return;
    boxes.forEach(sel => {
      const inp = tr.querySelector(sel);
      if(inp && isBlank(inp.value)){ inp.classList.add('missing'); bad.push(inp); }
    });
  });
  return bad;
}

function setBusy(btn, busy){
  btn.classList.toggle('is-busy', busy);
  btn.disabled = busy;
}

function toast(msg, kind){
  const t = document.createElement('div');
  t.className = 'toast ' + (kind||'');
  t.setAttribute('role', kind === 'err' ? 'alert' : 'status');
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(()=>t.remove(), kind==='err' ? 6000 : 3500);
}

async function loadState(){
  const r = await fetch('/api/state'); STATE = await r.json();
  $('wbname').textContent = STATE.workbook;
  $('wbchip').classList.toggle('is-hidden', !STATE.workbook);
  const s = STATE.settings;
  $('min_float').value = s.min_float;
  $('gap_threshold').value = s.gap_threshold;
  $('require_gap_explanation').checked = s.require_gap_explanation;
  $('zelty_mode').value = s.zelty_mode;
  $('modepill').classList.toggle('is-hidden', s.zelty_mode === 'api');
  if (STATE.suggested_date) $('date').value = STATE.suggested_date;
}

$('saveSettings').onclick = async () => {
  const btn = $('saveSettings');
  const body = {
    min_float: parseFloat($('min_float').value),
    gap_threshold: parseFloat($('gap_threshold').value),
    require_gap_explanation: $('require_gap_explanation').checked,
    zelty_mode: $('zelty_mode').value,
  };
  setBusy(btn, true);
  try{
    const r = await fetch('/api/settings', {method:'POST',
      headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    STATE.settings = await r.json();
    $('modepill').classList.toggle('is-hidden', STATE.settings.zelty_mode === 'api');
    toast('Settings saved.', 'good');
  } finally { setBusy(btn, false); }
};

function renderSkeleton(){
  $('gridCard').classList.remove('is-hidden');
  $('gridDate').textContent = 'loading…';
  $('gapSummary').textContent = '';
  const tb = $('grid').querySelector('tbody');
  const n = (STATE && STATE.sites && STATE.sites.length) || 5;
  const cell = cls => `<td><span class="skel ${cls}"></span></td>`;
  tb.innerHTML = Array.from({length:n}).map(() =>
    `<tr>
       <td><span class="skel skel-name"></span>
         <span class="skel skel-sub"></span></td>
       ${cell('skel-56')}${cell('skel-70')}${cell('skel-70')}${cell('skel-56')}${cell('skel-56')}${cell('skel-64')}
     </tr>`).join('');
}

let REVEALED = false;       // has the user submitted counts and revealed Zelty?
let RECOMPUTERS = [];       // per-row gap recompute callbacks

$('populate').onclick = async () => {
  const btn = $('populate');
  const date = $('date').value;
  if(!date){ toast('Pick a date first.', 'err'); return; }
  setBusy(btn, true);
  renderSkeleton();
  try{
    const r = await fetch('/api/populate', {method:'POST',
      headers:{'Content-Type':'application/json'}, body:JSON.stringify({date})});
    const data = await r.json();
    if(!r.ok){
      toast(data.error||'Populate failed.', 'err');
      $('gridCard').classList.add('is-hidden');
      return;
    }
    renderGrid(data);
  } catch(e){
    toast('Could not reach the server.', 'err');
    $('gridCard').classList.add('is-hidden');
  } finally { setBusy(btn, false); }
};

function renderGrid(data){
  $('gridCard').classList.remove('is-hidden');
  $('gridDate').textContent = data.date + (data.mode!=='api' ? '  ·  no Zelty feed' : '');
  // Back to the "enter counts" phase every time we (re)load a day.
  REVEALED = false;
  RECOMPUTERS = [];
  $('grid').classList.add('phase-input');
  $('reveal').classList.remove('is-hidden');
  $('write').classList.add('is-hidden');
  const tb = $('grid').querySelector('tbody');
  tb.innerHTML = '';
  const thr = STATE.settings.gap_threshold;
  data.rows.forEach(row => {
    const tr = document.createElement('tr');
    tr.dataset.site = row.site;
    if(row.duplicate) tr.classList.add('dup');
    tr.innerHTML = `
      <td>
        <span class="site-name">${row.site}${row.duplicate
          ? ' <span class="pill">already recorded</span>' : ''}</span>
        <span class="subrow">last ${row.last_date||'—'} · float was ${money(row.last_caisse)}</span>
      </td>
      <td>${money(row.caisse)}</td>
      <td><input type="text" inputmode="decimal" autocomplete="off" class="counted" placeholder="0.00 or –" value="${row.counted!=null?money(row.counted):''}" ${row.duplicate?'disabled':''}></td>
      <td><input type="text" inputmode="decimal" autocomplete="off" class="sortie" value="${money(row.sortie)}" ${row.duplicate?'disabled':''}></td>
      <td><input type="text" inputmode="decimal" autocomplete="off" class="depot" value="${money(row.depot)}" ${row.duplicate?'disabled':''}></td>
      <td class="reveal"><input type="text" inputmode="decimal" autocomplete="off" class="zelty" placeholder="0.00 or –" value="${row.zelty!=null?money(row.zelty):''}" ${row.duplicate?'disabled':''}></td>
      <td class="reveal gapcell"><span class="gap-badge is-skip">—</span></td>`;
    const cell = tr.querySelector('.gapcell');
    const explain = document.createElement('div');
    explain.className = 'explain';
    explain.innerHTML = `<textarea placeholder="Explain the gap…"></textarea>`;
    tr.querySelector('td:first-child').appendChild(explain);

    function recompute(){
      if(!REVEALED){ updateSummary(); return; }   // gap hidden until submit; keep count progress live
      const badge = cell.querySelector('.gap-badge');
      const zRaw = tr.querySelector('.zelty').value;
      const hRaw = tr.querySelector('.counted').value;
      // No data for either side → nothing to reconcile; never a gap.
      if(isNoData(zRaw) || isNoData(hRaw)){
        badge.textContent = 'no data';
        badge.className = 'gap-badge is-skip';
        tr.classList.remove('gap', 'ok', 'needexplain');
        updateSummary();
        return;
      }
      const z = cellNum(zRaw);
      const h = cellNum(hRaw);
      const gap = z - h;
      const big = Math.abs(gap) >= thr;
      badge.textContent = (gap>=0?'+':'') + money(gap);
      badge.className = 'gap-badge ' + (big ? 'is-gap' : 'is-zero');
      if(row.duplicate){
        // Already recorded in the sheet — show its real gap, read-only, and
        // don't require an explanation (it isn't being re-written).
        return;
      }
      tr.classList.toggle('gap', big);
      tr.classList.toggle('ok', !big);
      tr.classList.toggle('needexplain', big && STATE.settings.require_gap_explanation);
      const ta = explain.querySelector('textarea');
      ta.placeholder = `Explain the ${(gap>=0?'+':'')+money(gap)} gap (saved as "${data.date} — …")`;
      explain.classList.toggle('filled', ta.value.trim().length>0);
      updateSummary();
    }
    tr.querySelectorAll('input').forEach(i=>i.addEventListener('input', ()=>{
      i.classList.remove('missing');
      recompute();
    }));
    explain.querySelector('textarea').addEventListener('input', ()=>{
      explain.classList.toggle('filled', explain.querySelector('textarea').value.trim().length>0);
      updateSummary();
    });
    tb.appendChild(tr);
    RECOMPUTERS.push(recompute);
  });
  updateSummary();
}

// Phase 2: user has entered counts — reveal Zelty and compute the gaps.
$('reveal').onclick = () => {
  // Every box must hold a value or "-" (no data) before we reveal.
  const bad = flagIncomplete();
  if(bad.length){
    toast('Data is not complete — enter a value, or “–” where there is no data.', 'err');
    bad[0].focus();
    return;
  }
  REVEALED = true;
  $('grid').classList.remove('phase-input');
  $('reveal').classList.add('is-hidden');
  $('write').classList.remove('is-hidden');
  RECOMPUTERS.forEach(fn => fn());
  updateSummary();
};

function collectRows(){
  return [...$('grid').querySelectorAll('tbody tr')]
    .filter(tr => !tr.classList.contains('dup'))
    .map(tr => {
      const zRaw = tr.querySelector('.zelty').value;
      const hRaw = tr.querySelector('.counted').value;
      const noData = isNoData(zRaw) || isNoData(hRaw);
      let comment = (tr.querySelector('.explain textarea').value||'').trim();
      // A "-" row has no real figure to reconcile; record why so the gap
      // guard doesn't block it and the sheet says it was a no-data day.
      if(noData && !comment) comment = 'no data';
      return {
        site: tr.dataset.site,
        zelty: cellNum(zRaw),
        counted: cellNum(hRaw),
        sortie: cellNum(tr.querySelector('.sortie').value),
        depot: cellNum(tr.querySelector('.depot').value),
        comment,
        noData,
      };
    });
}

function updateSummary(){
  const el = $('gapSummary');
  if(!REVEALED){
    const entered = [...$('grid').querySelectorAll('tbody tr:not(.dup) .counted')]
      .filter(i => i.value.trim() !== '').length;
    const total = $('grid').querySelectorAll('tbody tr:not(.dup)').length;
    el.textContent = `${entered}/${total} counts entered`;
    el.classList.remove('has-unexplained');
    return;
  }
  const thr = STATE.settings.gap_threshold;
  const rows = collectRows();
  const gaps = rows.filter(r => !r.noData && Math.abs(r.zelty-r.counted) >= thr);
  const unexplained = gaps.filter(r => !r.comment).length;
  el.textContent = `${gaps.length} gap${gaps.length===1?'':'s'}`
    + (unexplained ? ` · ${unexplained} unexplained` : '');
  el.classList.toggle('has-unexplained', unexplained>0);
  $('write').disabled = STATE.settings.require_gap_explanation && unexplained>0;
}

$('write').onclick = async () => {
  const btn = $('write');
  const date = $('date').value;
  const bad = flagIncomplete();
  if(bad.length){
    toast('Data is not complete — enter a value, or “–” where there is no data.', 'err');
    bad[0].focus();
    return;
  }
  const rows = collectRows();
  if(!rows.length){ toast('Nothing to write.', 'err'); return; }
  setBusy(btn, true);
  try{
    const r = await fetch('/api/write', {method:'POST',
      headers:{'Content-Type':'application/json'}, body:JSON.stringify({date, rows})});
    const data = await r.json();
    if(!r.ok){ toast(data.error||'Write failed.', 'err'); return; }
    const wrote = data.results.filter(x=>x.written).length;
    const skipped = data.results.length - wrote;
    toast(`Wrote ${wrote} row${wrote===1?'':'s'}${skipped?`, ${skipped} skipped`:''}. Reloading…`, 'good');
    setTimeout(async ()=>{ await loadState(); $('populate').click(); }, 1200);
  } catch(e){
    toast('Could not reach the server.', 'err');
  } finally { setBusy(btn, false); }
};

loadState();

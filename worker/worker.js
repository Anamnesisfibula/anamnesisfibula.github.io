// Suggest-alt API for the enemy tracker. Anyone can suggest and vote; only the admin (ADMIN_KEY) can approve.
const ORIGIN = 'https://anamnesisfibula.github.io';
const RAW = 'https://raw.githubusercontent.com/Anamnesisfibula/anamnesisfibula.github.io/data/network.json';
const OT = 'https://opentibia.info';
const LIMITS = { suggest: [5, 3600], vote: [60, 3600], lookup: [60, 600], names: [150, 600], admin: [20, 600] };

const cors = { 'Access-Control-Allow-Origin': ORIGIN, 'Access-Control-Allow-Methods': 'GET,POST,OPTIONS', 'Access-Control-Allow-Headers': 'Content-Type', 'Vary': 'Origin' };
const json = (o, st = 200, extra = {}) => new Response(JSON.stringify(o), { status: st, headers: { 'Content-Type': 'application/json', ...cors, ...extra } });
const err = (m, st = 400) => json({ error: m }, st);
const clean = (s, n) => String(s ?? '').replace(/[\u0000-\u001f\u007f]/g, ' ').replace(/\s+/g, ' ').trim().slice(0, n);

async function sha(s) { const b = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s)); return [...new Uint8Array(b)].map(x => x.toString(16).padStart(2, '0')).join('').slice(0, 24); }
function safeEq(a, b) { a = String(a || ''); b = String(b || ''); if (!b || a.length !== b.length) return false; let r = 0; for (let i = 0; i < a.length; i++) r |= a.charCodeAt(i) ^ b.charCodeAt(i); return r === 0; }

async function limited(env, kind, iph) {
  const [max, win] = LIMITS[kind]; const k = kind + ':' + iph; const t = Math.floor(Date.now() / 1000);
  const row = await env.DB.prepare('SELECT n, reset FROM rl WHERE k=?').bind(k).first();
  if (!row || row.reset < t) { await env.DB.prepare('INSERT OR REPLACE INTO rl (k,n,reset) VALUES (?,1,?)').bind(k, t + win).run(); return false; }
  if (row.n >= max) return true;
  await env.DB.prepare('UPDATE rl SET n=n+1 WHERE k=?').bind(k).run(); return false;
}

async function tracked() {
  const r = await fetch(RAW, { cf: { cacheTtl: 300, cacheEverything: true } });
  const n = await r.json(); const own = {};
  for (const [main, , alts] of n.clusters) { own[main] = main; for (const a of alts) own[a[0]] = main; }
  return own;
}

async function lookup(name) {
  const c = await fetch(OT + '/index/server/fibula', { redirect: 'manual' });
  const cookie = (c.headers.get('set-cookie') || '').split(/,(?=[^;]+=)/).map(x => x.split(';')[0].trim()).join('; ');
  const r = await fetch(OT + '/stats/player/' + encodeURIComponent(name), { headers: { cookie } });
  if (!r.ok) return null;
  const h = await r.text(); const t = (h.match(/<table[\s\S]*?<\/table>/) || [''])[0];
  const cells = (t.match(/<td[\s\S]*?<\/td>/g) || []).map(x => x.replace(/<[^>]+>/g, ' ').replace(/&#039;|&apos;/g, "'").replace(/&amp;/g, '&').replace(/\s+/g, ' ').trim());
  const i = cells.findIndex(x => /Voc:/.test(x)); if (i < 0) return null;
  const info = cells[i]; const voc = (info.match(/Voc: (.+?) Town/) || [])[1] || '';
  const nm = clean(info.split('|')[0], 40) || name; const g = (info.match(/Guild: (.*?)\s*of (.+)$/) || [])[2] || '';
  return { name: nm, level: parseInt(cells[i + 1]) || 0, voc, guild: g.trim() };
}

async function list(env) {
  const { results } = await env.DB.prepare(`SELECT s.id, s.char, s.main, s.owner, s.comment, s.lvl, s.voc, s.created, s.status, s.note, s.imported,
    COALESCE(SUM(CASE WHEN v.v=1 THEN 1 END),0) AS up, COALESCE(SUM(CASE WHEN v.v=-1 THEN 1 END),0) AS down
    FROM sug s LEFT JOIN votes v ON v.sid=s.id WHERE s.status!='deleted' GROUP BY s.id ORDER BY s.id DESC LIMIT 300`).all();
  return results;
}

export default {
  async fetch(req, env) {
    if (req.method === 'OPTIONS') return new Response(null, { headers: cors });
    const u = new URL(req.url); const p = u.pathname;
    const iph = await sha((req.headers.get('CF-Connecting-IP') || '') + '|' + env.ADMIN_KEY);
    let body = {};
    if (req.method === 'POST') { try { body = await req.json(); } catch { return err('bad json'); } }
    try {
      if (p === '/suggestions' && req.method === 'GET') return json(await list(env), 200, { 'Cache-Control': 'no-store' });

      if (p === '/names' && req.method === 'GET') {
        const q = clean(u.searchParams.get('q'), 30); if (q.length < 2) return json([]);
        const ck = new Request('https://cache.local/names/' + encodeURIComponent(q.toLowerCase()));
        const hit = await caches.default.match(ck); if (hit) { const r = new Response(hit.body, hit); for (const [k, v] of Object.entries(cors)) r.headers.set(k, v); return r; }
        if (await limited(env, 'names', iph)) return err('Too many searches, wait a few minutes.', 429);
        const r = await fetch(OT + '/count/name/fibula', { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: 'name=' + encodeURIComponent(q) });
        let list = []; try { list = JSON.parse(await r.text()) || []; } catch { }
        list = (Array.isArray(list) ? list : []).filter(x => typeof x === 'string').slice(0, 30);
        const res = json(list, 200, { 'Cache-Control': 'public, max-age=3600' });
        await caches.default.put(ck, res.clone()); return res;
      }

      if (p === '/lookup' && req.method === 'GET') {
        if (await limited(env, 'lookup', iph)) return err('Too many lookups, wait a few minutes.', 429);
        const n = clean(u.searchParams.get('name'), 40); if (!n) return err('name missing');
        const r = await lookup(n); if (!r) return err('Character not found on opentibia.info', 404);
        const own = await tracked(); return json({ ...r, tracked: !!own[r.name], owner: own[r.name] || null });
      }

      if (p === '/suggest' && req.method === 'POST') {
        const ch = clean(body.char, 40), mainIn = clean(body.main, 40), comment = clean(body.comment, 300);
        if (!ch || !mainIn) return err('Both character and main are needed.');
        if (comment.length < 3) return err('Please write a short comment on why.');
        if (await limited(env, 'suggest', iph)) return err('Too many suggestions from you, try again in an hour.', 429);
        const own = await tracked();
        if (!own[mainIn]) return err('The main has to be a character we already track.');
        const r = await lookup(ch); if (!r) return err('That character was not found on opentibia.info.', 404);
        if (own[r.name]) return err(r.name + ' is already tracked (under ' + own[r.name] + ').');
        const dup = await env.DB.prepare("SELECT id FROM sug WHERE char=? AND status='open'").bind(r.name).first();
        if (dup) return err(r.name + ' is already suggested. Vote on that suggestion instead.');
        const created = new Date().toISOString().slice(0, 16).replace('T', ' ');
        await env.DB.prepare('INSERT INTO sug (char, main, owner, comment, lvl, voc, created, iph) VALUES (?,?,?,?,?,?,?,?)')
          .bind(r.name, mainIn, own[mainIn], comment, r.level, r.voc, created, iph).run();
        return json({ ok: true, char: r.name });
      }

      if (p === '/vote' && req.method === 'POST') {
        const sid = parseInt(body.id), v = [1, -1, 0].includes(body.v) ? body.v : null, voter = clean(body.voter, 64);
        if (!sid || v === null || voter.length < 16) return err('bad vote');
        if (await limited(env, 'vote', iph)) return err('Too many votes, try again later.', 429);
        const s = await env.DB.prepare("SELECT status FROM sug WHERE id=?").bind(sid).first();
        if (!s || s.status !== 'open') return err('Voting is closed for this suggestion.');
        const other = await env.DB.prepare('SELECT 1 FROM votes WHERE sid=? AND iph=? AND voter!=?').bind(sid, iph, voter).first();
        if (other) return err('Someone on your network has already voted on this one.', 409);
        if (v === 0) await env.DB.prepare('DELETE FROM votes WHERE sid=? AND voter=?').bind(sid, voter).run();
        else await env.DB.prepare('INSERT OR REPLACE INTO votes (sid, voter, iph, v) VALUES (?,?,?,?)').bind(sid, voter, iph, v).run();
        return json({ ok: true });
      }

      // ---- admin ----
      if (p.startsWith('/admin/')) {
        const key = req.method === 'POST' ? body.key : u.searchParams.get('key');
        if (!safeEq(key, env.ADMIN_KEY)) { await limited(env, 'admin', iph); return err('Wrong admin key.', 403); }
        if (p === '/admin/check') return json({ ok: true });
        if (p === '/admin/set' && req.method === 'POST') {
          const sid = parseInt(body.id), st = body.status;
          if (!sid || !['open', 'approved', 'rejected', 'deleted'].includes(st)) return err('bad status');
          await env.DB.prepare('UPDATE sug SET status=?, note=? WHERE id=?').bind(st, clean(body.note, 300), sid).run();
          return json({ ok: true });
        }
        if (p === '/admin/approved') { const { results } = await env.DB.prepare("SELECT id, char, main, owner, comment FROM sug WHERE status='approved' AND imported=0").all(); return json(results); }
        if (p === '/admin/imported' && req.method === 'POST') {
          for (const id of (body.ids || []).map(Number).filter(Boolean)) await env.DB.prepare('UPDATE sug SET imported=1 WHERE id=?').bind(id).run();
          return json({ ok: true });
        }
      }
      return err('not found', 404);
    } catch (e) { return err('Server error: ' + e.message, 500); }
  }
};

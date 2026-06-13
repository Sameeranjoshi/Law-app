/* =====================================================================
   Joshi & Associates — local backend
   Holds the eCourtsIndia API key server-side (never sent to the browser),
   proxies court-data calls, and serves the web app.

   Run:  node server.js   (Node 18+)  then open http://localhost:8787
   ===================================================================== */
const http = require('http');
const fs   = require('fs');
const path = require('path');

/* ---- load .env (tiny parser, no dependency) ---- */
(function loadEnv(){
  try{
    fs.readFileSync(path.join(__dirname, '.env'), 'utf8').split('\n').forEach(line=>{
      const m = line.match(/^\s*([A-Za-z0-9_]+)\s*=\s*(.*)\s*$/);
      if(m && !process.env[m[1]]) process.env[m[1]] = m[2].replace(/^["']|["']$/g,'').trim();
    });
  }catch(e){ /* no .env file — rely on real env vars */ }
})();

const API_KEY  = process.env.ECI_API_KEY || '';
const UPSTREAM  = 'https://webapi.ecourtsindia.com';
const PORT      = process.env.PORT || 8787;

if(!API_KEY) console.warn('\n⚠  ECI_API_KEY is not set. Court lookups will return an error.\n   Add it to a .env file:  ECI_API_KEY=eci_live_xxx\n');

const MIME = {'.html':'text/html','.js':'text/javascript','.css':'text/css','.json':'application/json','.svg':'image/svg+xml','.ico':'image/x-icon','.png':'image/png'};

function send(res, status, body, headers={}){
  res.writeHead(status, Object.assign({
    'Access-Control-Allow-Origin':'*',
    'Access-Control-Allow-Headers':'Content-Type',
    'Access-Control-Allow-Methods':'GET,POST,OPTIONS'
  }, headers));
  res.end(body);
}
const sendJson = (res, status, obj) => send(res, status, JSON.stringify(obj), {'Content-Type':'application/json'});

async function upstream(method, urlPath, bodyObj){
  const r = await fetch(UPSTREAM + urlPath, {
    method,
    headers: Object.assign(
      {'Authorization':'Bearer '+API_KEY, 'Accept':'application/json'},
      bodyObj ? {'Content-Type':'application/json'} : {}
    ),
    body: bodyObj ? JSON.stringify(bodyObj) : undefined
  });
  const text = await r.text();
  let data; try{ data = JSON.parse(text); }catch(e){ data = {raw:text}; }
  return { status: r.status, data };
}
function readBody(req){
  return new Promise(resolve=>{ let d=''; req.on('data',c=>d+=c); req.on('end',()=>{ try{ resolve(d?JSON.parse(d):{}); }catch(e){ resolve({}); } }); });
}

const server = http.createServer(async (req,res)=>{
  const u = new URL(req.url, 'http://localhost');
  const p = u.pathname;
  if(req.method==='OPTIONS') return send(res,204,'');

  /* ---------- API proxy ---------- */
  if(p.startsWith('/api/')){
    if(!API_KEY) return sendJson(res,500,{error:{message:'Backend has no ECI_API_KEY. Add it to .env and restart the server.'}});
    try{
      let m;
      // GET /api/case/:cnr  → case detail
      if((m = p.match(/^\/api\/case\/([A-Za-z0-9]+)$/)) && req.method==='GET'){
        const out = await upstream('GET', '/api/partner/case/'+encodeURIComponent(m[1]));
        return sendJson(res, out.status, out.data);
      }
      // GET /api/search?advocate=&query=&courtCodes=&caseStatuses= → case search
      if(p==='/api/search' && req.method==='GET'){
        const qs = new URLSearchParams();
        if(u.searchParams.get('advocate')) qs.set('advocates', u.searchParams.get('advocate'));
        if(u.searchParams.get('query'))    qs.set('query',     u.searchParams.get('query'));
        if(u.searchParams.get('litigants'))qs.set('litigants', u.searchParams.get('litigants'));
        ['courtCodes','caseStatuses'].forEach(k=> u.searchParams.getAll(k).forEach(v=> qs.append(k,v)) );
        qs.set('pageSize', u.searchParams.get('pageSize') || '25');
        const out = await upstream('GET','/api/partner/search?'+qs.toString());
        return sendJson(res, out.status, out.data);
      }
      // POST /api/refresh/:cnr  → queue a fresh scrape
      if((m = p.match(/^\/api\/refresh\/([A-Za-z0-9]+)$/)) && req.method==='POST'){
        const out = await upstream('POST','/api/partner/case/'+encodeURIComponent(m[1])+'/refresh');
        return sendJson(res, out.status, out.data);
      }
      // POST /api/bulk-refresh  { cnrs:[...] }
      if(p==='/api/bulk-refresh' && req.method==='POST'){
        const body = await readBody(req);
        const out = await upstream('POST','/api/partner/case/bulk-refresh', {cnrs: body.cnrs||[]});
        return sendJson(res, out.status, out.data);
      }
      // GET /api/cs/<rest> → court structure (free, no billing): states / districts / complexes / courts
      if((m = p.match(/^\/api\/cs\/(.+)$/)) && req.method==='GET'){
        const out = await upstream('GET','/api/partner/causelist/court-structure/'+m[1]);
        return sendJson(res, out.status, out.data);
      }
      // GET /api/causelist?state=&districtCode=&courtComplexCode=&date=&advocate= → cause list search
      if(p==='/api/causelist' && req.method==='GET'){
        const qs=new URLSearchParams();
        ['state','districtCode','courtComplexCode','court','courtNo','date','startDate','endDate','advocate','litigant','judge','listType','limit','offset','q']
          .forEach(k=>{ const v=u.searchParams.get(k); if(v) qs.set(k,v); });
        if(!qs.get('limit')) qs.set('limit','50');
        const out=await upstream('GET','/api/partner/causelist/search?'+qs.toString());
        return sendJson(res, out.status, out.data);
      }
      // GET /api/causelist-dates?state=&districtCode=... → which dates have data
      if(p==='/api/causelist-dates' && req.method==='GET'){
        const qs=new URLSearchParams();
        ['state','districtCode','courtComplexCode','court','courtNo'].forEach(k=>{ const v=u.searchParams.get(k); if(v) qs.set(k,v); });
        const out=await upstream('GET','/api/partner/causelist/available-dates?'+qs.toString());
        return sendJson(res, out.status, out.data);
      }
      return sendJson(res,404,{error:{message:'Unknown API route'}});
    }catch(e){
      return sendJson(res,502,{error:{message:'Could not reach eCourtsIndia: '+e.message}});
    }
  }

  /* ---------- static files ---------- */
  let file = (p==='/' ? '/index.html' : p).replace(/\.\.+/g,'');
  const fp = path.join(__dirname, file);
  fs.readFile(fp, (err,buf)=>{
    if(err) return send(res,404,'Not found');
    send(res,200,buf,{'Content-Type': MIME[path.extname(fp)] || 'application/octet-stream'});
  });
});

server.listen(PORT, ()=> console.log('\n▲  Joshi office app running →  http://localhost:'+PORT+'\n'));

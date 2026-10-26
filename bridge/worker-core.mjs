// A fixed HTTPS origin only. Client input can never choose an upstream host.
export function createBridgeHandler({fetchUpstream = fetch} = {}) {
  return async function handle(request, env) {
    const url = new URL(request.url);
    let origin;
    try { origin = new URL(env.UPSTREAM_ORIGIN || env.RAILWAY_ORIGIN); } catch { return new Response('Not configured', {status:503}); }
    if (origin.protocol !== 'https:' || !/^(?:[a-z0-9-]+\.up\.railway\.app|[a-z0-9-]+(?:\.[a-z0-9-]+)*\.bot-hosting\.(?:net|cloud))$/.test(origin.hostname) || origin.port || origin.pathname !== '/' || origin.search || origin.username || origin.password || !/^[A-Za-z0-9_-]{32,128}$/.test(env.BRIDGE_TOKEN || '')) return new Response('Not configured', {status:503});
    if (!['GET','HEAD','POST','DELETE'].includes(request.method)) return new Response('Method not allowed', {status:405});
    if (request.headers.has('Upgrade')) return new Response('HTTPS carrier required', {status:426});
    if (Number(request.headers.get('Content-Length') || 0) > 1048576) return new Response('Too large', {status:413});
    let body;
    if (request.method !== 'GET' && request.method !== 'HEAD') {
      const chunks=[]; let length=0;
      const reader=request.body?.getReader();
      if (reader) {
        for (;;) { const {value,done}=await reader.read(); if(done) break; length+=value.byteLength;
          if(length>1048576) { await reader.cancel(); return new Response('Too large',{status:413}); } chunks.push(value); }
      }
      body=new Uint8Array(length); let offset=0;
      for(const chunk of chunks) { body.set(chunk,offset); offset+=chunk.byteLength; }
    }
    const headers=new Headers(request.headers);
    for (const key of ['Cookie','Host','Forwarded','X-Forwarded-For','X-Forwarded-Host','X-Forwarded-Proto','X-Bridge-Token','X-Bridge-Client-IP','Connection','Transfer-Encoding','Content-Length','Accept-Encoding']) headers.delete(key);
    headers.set('X-Bridge-Token',env.BRIDGE_TOKEN);
    headers.set('X-Bridge-Client-IP',request.headers.get('CF-Connecting-IP') || '127.0.0.1');
    headers.set('Accept-Encoding','identity');
    if(body) headers.set('Content-Length',String(body.byteLength));
    try {
      const upstream=await fetchUpstream(origin.origin+'/_webbridge'+url.pathname+url.search, {
        method:request.method,headers,body,redirect:'manual',signal:AbortSignal.timeout(45000), cf:{cacheTtl:0,cacheEverything:false}
      });
      const responseHeaders=new Headers(upstream.headers);
      responseHeaders.delete('Set-Cookie'); responseHeaders.set('Cache-Control','no-store');
      return new Response(upstream.body,{status:upstream.status,headers:responseHeaders});
    } catch { return new Response('Bridge unavailable',{status:502}); }
  };
}

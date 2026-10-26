import test from 'node:test';
import assert from 'node:assert/strict';
import { createBridgeHandler } from '../bridge/worker-core.mjs';
import standalone, {createBridgeHandler as createStandaloneHandler} from '../bridge/worker-standalone.mjs';
import {readFileSync} from 'node:fs';
const env={RAILWAY_ORIGIN:'https://example-production.up.railway.app',BRIDGE_TOKEN:'a'.repeat(43)};
test('Bot-Hosting origin is supported without accepting arbitrary destination hosts',async()=>{
 let destination;
 const handler=createBridgeHandler({fetchUpstream:async(url)=>{destination=url;return new Response('ok');}});
 const result=await handler(new Request('https://worker.example/'),{UPSTREAM_ORIGIN:'https://blueknight.apps.bot-hosting.cloud',BRIDGE_TOKEN:env.BRIDGE_TOKEN});
 assert.equal(result.status,200);
 assert.equal(destination,'https://blueknight.apps.bot-hosting.cloud/_webbridge/');
 assert.equal((await handler(new Request('https://worker.example/'),{UPSTREAM_ORIGIN:'http://localhost',BRIDGE_TOKEN:env.BRIDGE_TOKEN})).status,503);
});
test('standalone is self-contained, matches the tested core, and forwards binary traffic',async()=>{
 const source=readFileSync(new URL('../bridge/worker-standalone.mjs',import.meta.url),'utf8');
 const core=readFileSync(new URL('../bridge/worker-core.mjs',import.meta.url),'utf8');
 assert.ok(source.includes(core));
 assert.doesNotMatch(source,/^\s*import\s/m);
 assert.equal(typeof standalone.fetch,'function');
 let called=false;
 const handler=createStandaloneHandler({fetchUpstream:async(url,init)=>{
   called=true;assert.equal(url,env.RAILWAY_ORIGIN+'/_webbridge/api/v1/up');
   assert.equal(init.headers.get('X-Bridge-Token'),env.BRIDGE_TOKEN);
   assert.deepEqual([...init.body],[1,2,3]);
   return new Response(null,{status:204});
 }});
 assert.equal((await handler(new Request('https://worker.example/api/v1/up',{method:'POST',body:new Uint8Array([1,2,3])}),env)).status,204);
 assert.equal(called,true);
});
test('fixed Railway origin and unsupported transports', async()=>{
 let calls=0;
 const handle=createBridgeHandler({fetchUpstream:async()=>{calls++; return new Response('ok');}});
 const req=new Request('https://worker.example/');
 assert.equal((await handle(req,{...env,RAILWAY_ORIGIN:'https://evil.example'})).status,503);
 assert.equal((await handle(req,{...env,BRIDGE_TOKEN:''})).status,503);
 assert.equal((await handle(new Request('https://worker.example/',{headers:{Upgrade:'websocket'}}),env)).status,426);
 assert.equal(calls,0);
});
test('binary body, credentials and sequence headers survive; spoofed forwarding and cookies do not',async()=>{
 let captured;
 const handle=createBridgeHandler({fetchUpstream:async(url,init)=>{captured={url,init};return new Response(new Uint8Array([17,0,0]),{headers:{'X-Session-Token':'session','Content-Security-Policy':"script-src 'nonce-x'"}});}});
 const response=await handle(new Request('https://worker.example/api/v1/up',{method:'POST',body:new Uint8Array([1,2,3]),headers:{Authorization:'Bearer session','X-Up-Seq':'1','CF-Connecting-IP':'1.2.3.4','X-Bridge-Token':'attacker','X-Bridge-Client-IP':'attacker',Cookie:'panel=private','X-Forwarded-For':'attacker'}}),env);
 assert.equal(captured.url,env.RAILWAY_ORIGIN+'/_webbridge/api/v1/up');
 assert.deepEqual([...captured.init.body],[1,2,3]);
 assert.equal(captured.init.headers.get('X-Bridge-Token'),env.BRIDGE_TOKEN);
 assert.equal(captured.init.headers.get('X-Bridge-Client-IP'),'1.2.3.4');
 assert.equal(captured.init.headers.get('Cookie'),null);
 assert.equal(captured.init.headers.get('X-Forwarded-For'),null);
 assert.equal(captured.init.headers.get('Authorization'),'Bearer session');
 assert.equal(captured.init.headers.get('X-Up-Seq'),'1');
 assert.equal(response.headers.get('X-Session-Token'),'session');
 assert.equal(response.headers.get('Content-Security-Policy'),"script-src 'nonce-x'");
});
test('query targets cannot override the upstream; redirects are not followed',async()=>{
 let target,mode;
 const handle=createBridgeHandler({fetchUpstream:async(url,init)=>{target=url;mode=init.redirect;return new Response(null,{status:302,headers:{Location:'https://elsewhere.example'}});}});
 assert.equal((await handle(new Request('https://worker.example/?host=evil.example'),env)).status,302);
 assert.ok(target.startsWith(env.RAILWAY_ORIGIN+'/_webbridge/'));
 assert.equal(mode,'manual');
});
test('oversized payload and upstream failure are bounded',async()=>{
 const handle=createBridgeHandler({fetchUpstream:async()=>{throw Error('unavailable');}});
 assert.equal((await handle(new Request('https://worker.example/'),env)).status,502);
 assert.equal((await handle(new Request('https://worker.example/api/v1/up',{method:'POST',body:new Uint8Array(1048577)}),env)).status,413);
});

import {test} from "node:test";
import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import ts from "typescript";
const compile = async name => ts.transpileModule(await readFile(new URL(`../src/${name}.ts`,import.meta.url),"utf8"),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const url = text => `data:text/javascript;base64,${Buffer.from(text).toString("base64")}`;
const auditUrl=url(await compile("reviewAudit"));
const audit=await import(auditUrl);
const adapter=await import(url((await compile("incidentThreads")).replace('"./reviewAudit"',JSON.stringify(auditUrl))));
const source={id:"sample",kind:"restricted_zone",title:"Motion near restricted area",room:"Playroom",status:"open",opened_at:"2026-10-24T09:00:28Z",media_time_ms:28000,media_end_time_ms:46000,observations:["Someone approached the doorway."],origin:"fixture",priority:"medium",demo_response:[{time_ms:31000,tool:"Notification",description:"Maya was notified."}]};
const context={cameraId:"CAM 01",cameraName:"Playroom",recordingStartedAt:"2026-10-24T09:00:00Z"};
test("adapter derives wall-clock threads without mutating source",()=>{
  const before=JSON.stringify(source);const thread=adapter.adaptIncidentThread(source,context);
  assert.equal(thread.startedAt,"2026-10-24T09:00:28.000Z");assert.equal(thread.messages[1].at,"2026-10-24T09:00:31.000Z");
  assert.equal(thread.title,"Someone near the doorway");assert.equal(thread.messages[0].confidence,undefined);assert.equal(thread.source,source);assert.equal(JSON.stringify(source),before);
});
test("known incident start anchors offsets when recording metadata is absent",()=>{
  const thread=adapter.adaptIncidentThread(source,{cameraId:"cam",cameraName:"Playroom"});
  assert.equal(thread.startedAt,"2026-10-24T09:00:28.000Z");assert.equal(thread.messages[1].at,"2026-10-24T09:00:31.000Z");
});
test("anchored notes and resolution are session overlays with audit records",()=>{
  const note=adapter.addIncidentNote({incidentId:source.id,cameraId:"CAM 01",userId:"maya",authorName:"Maya",text:"  Checked the gate.  ",at:"2026-10-24T10:00:00Z",anchorAt:"2026-10-24T09:00:35Z",anchorSeconds:35});
  assert.equal(note.text,"Checked the gate.");assert.equal(note.anchorSeconds,35);
  const {resolution,message}=adapter.resolveIncidentThread({incidentId:source.id,cameraId:"CAM 01",userId:"maya",outcome:"handled",at:"2026-10-24T10:01:00Z"});
  const thread=adapter.adaptIncidentThread(source,{...context,changes:{messages:[note,message],resolution,lastReadAt:message.at}});
  assert.equal(thread.status,"resolved");assert.equal(thread.resolution.outcome,"handled");assert.equal(thread.messages.filter(m=>m.kind==="detection").length,1);assert.equal(thread.messages.filter(m=>m.kind==="note").length,1);assert.equal(source.status,"open");
  assert.deepEqual(audit.reviewActivity("CAM 01").map(e=>e.action),["add_note","resolve_incident"]);
});
test("reject empty or oversized notes before auditing",()=>{
  assert.throws(()=>adapter.addIncidentNote({incidentId:"x",cameraId:"c",userId:"u",authorName:"U",text:"   "}));
  assert.throws(()=>adapter.addIncidentNote({incidentId:"x",cameraId:"c",userId:"u",authorName:"U",text:"x".repeat(2001)}));
});
test("closed backend incidents map to resolved without making up an outcome",()=>{
  const thread=adapter.adaptIncidentThread({...source,status:"dismissed",resolved_at:"2026-10-24T09:00:46Z",assigned_responder:"Maya"},context);
  assert.equal(thread.status,"resolved");assert.equal(thread.resolution,undefined);assert.match(thread.messages.at(-1).text,/Maya dismissed/);
});

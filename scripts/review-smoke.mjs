import assert from "node:assert/strict";
import { mkdir, readFile } from "node:fs/promises";
import { chromium } from "playwright";
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1323, height: 820 }, acceptDownloads: true });
const errors = [];
page.on("pageerror", e => errors.push(e.message));
const url = process.env.LOOKOUT_URL || "http://127.0.0.1:5175";
await mkdir("docs/ui-after", { recursive: true });
try {
  await page.goto(url);
  await page.getByRole("button", { name: "Pause playback", exact: true }).click();
  const slider = page.getByRole("slider", { name: "Video playback position", exact: true });
  assert.equal(await page.locator(".monitor-column > .playback").count(), 1);
  assert.equal(await page.locator(".monitor-grid > .playback, .playback-incident-key, .review-range, .timeline-scale, .role-chip").count(), 0);
  assert.match(await page.locator(".playback-clock").innerText(), /AM|PM/);
  for (const name of ["Mark incident", "In", "Out", "Save clip", "Snapshot"]) assert.equal(await page.getByRole("button", {name, exact: true}).count(), 0);
  await page.getByRole("button",{name:"Clip information",exact:true}).click();
  await page.getByText("Not supplied",{exact:true}).waitFor();
  assert.equal(await page.locator(".clip-details").evaluate(e=>e.matches(":popover-open")),true);
  assert.equal(await page.locator(".clip-details").evaluate(e=>{const r=e.getBoundingClientRect();return e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));}),true);
  await page.screenshot({path:"docs/ui-after/info-1323x820.png"}); await page.keyboard.press("Escape");
  assert.equal(await page.locator(".footage-kind").count(),0);
  assert.equal(await page.locator(".ruler-label").first().evaluate(e=>getComputedStyle(e).fontSize),"11px");
  await page.locator(".date-picker > summary").click();
  const today=page.locator(".calendar-days button.today");
  assert.equal(await today.getAttribute("aria-pressed"),"true");
  assert.equal(await today.evaluate(e=>getComputedStyle(e).color),"rgb(255, 255, 255)");
  assert.equal(await page.locator(".calendar-days i").count(),0);
  await page.locator(".calendar-days button:not(:disabled):not(.today)").first().click();
  await page.locator(".date-picker > summary").click();
  assert.equal(await today.evaluate(e=>getComputedStyle(e).color),"rgb(32, 129, 142)");
  assert.equal(await today.evaluate(e=>getComputedStyle(e).textDecorationLine),"none");
  await page.screenshot({path:"docs/ui-after/calendar-1323x820.png"});
  await page.getByRole("button",{name:"Today",exact:true}).click();
  const row = page.locator(".trace-summary").first(); await row.click();
  assert.equal(Number(await slider.inputValue()),28); assert.equal(await row.getAttribute("aria-expanded"),"true");
  assert.equal(await row.locator(".trace-thread-heading > strong").innerText(),"Incident");
  assert.match(await row.locator("img.trace-thumbnail").getAttribute("src"),/playroom/);
  await page.screenshot({path:"docs/ui-after/event-thread-1323x820.png"});

  await page.getByRole("button", {name:"Export details",exact:true}).click();
  assert.equal(await page.getByRole("button",{name:"Download",exact:true}).isDisabled(),true);
  await page.getByRole("textbox",{name:"Reason for export"}).fill("Caregiver review");
  const detailsDownload = page.waitForEvent("download"); await page.getByRole("button",{name:"Download",exact:true}).click();
  const details = await detailsDownload; const saved = JSON.parse(await readFile(await details.path(), "utf8"));
  assert.equal(saved.reason,"Caregiver review"); assert.equal(saved.incident.id,"demo-camera-0-0"); assert.ok(saved.exportedBy);
  assert.equal(await page.getByRole("button",{name:"Export clip",exact:true}).isDisabled(),true);
  await page.getByRole("button", {name:"Open", exact: true}).click(); await page.getByText("Nothing flagged on this day").waitFor();
  await page.getByRole("button", {name:"All", exact: true}).click();
  await page.getByRole("button", {name:/Jump to Activity flagged/}).click(); assert.equal(Number(await slider.inputValue()),83);
  await page.locator(".trace-summary").nth(1).focus(); await page.keyboard.press("ArrowUp"); assert.equal(await page.locator(".trace-summary").first().evaluate(e => e === document.activeElement),true);
  await page.locator(".play-button").focus(); await page.keyboard.press("."); assert.equal(Number(await slider.inputValue()),84);
  await page.keyboard.press("["); assert.equal(Number(await slider.inputValue()),83);
  await page.locator(".account-menu > summary").click(); await page.getByRole("button",{name:"Shortcuts",exact:true}).click();
  await page.getByRole("dialog",{name:"Keyboard shortcuts"}).waitFor(); await page.keyboard.press("Escape");
  await page.keyboard.press("?"); await page.getByRole("dialog",{name:"Keyboard shortcuts"}).waitFor(); await page.keyboard.press("Escape");
  for (const [width,height] of [[1323,820],[1920,1200],[1024,768]]) {
    await page.setViewportSize({width,height}); await page.reload(); await page.getByRole("button", {name:"Pause playback",exact:true}).click();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `${width}: horizontal overflow`);
    const order = await page.locator(".monitor-side-panel > details > summary").allTextContents(); assert.deepEqual(order.map(x=>x.replace(/\d/g,"").trim()), ["Date","Event trace","Cameras"]);
    const sidebar = await page.locator(".monitor-side-panel").boundingBox(); const frame = await page.locator(".monitor-column").boundingBox();
    assert.ok(Math.abs(sidebar.y + sidebar.height - frame.y - frame.height) < 3, `${width}: sidebar uses full video and timeline height`);
    const second = await page.locator(".trace-summary").nth(1).boundingBox(); const events = await page.locator(".trace-scroll").boundingBox(); assert.ok(second.y + second.height <= events.y + events.height + 1, `${width}: initial events visible`);
    const transport = await page.locator(".playback-top").boundingBox(); const timeline = await page.locator(".editor-timeline").boundingBox(); assert.ok(transport.y + transport.height <= timeline.y + 1);
    await page.screenshot({path:`docs/ui-after/${width}x${height}.png`});
    await page.locator(".sidebar-events > summary").click(); await page.locator(".monitor-side-panel > details:last-child > summary").click();
    const headers = await page.locator(".monitor-side-panel > details > summary").evaluateAll(es=>es.filter(e=>e.getBoundingClientRect().height).map(e=>({y:e.getBoundingClientRect().y,bottom:e.getBoundingClientRect().bottom})));
    assert.ok(headers[1].y - headers[0].bottom <= 4, "collapsed sections stay together at the top");
  }
  // Shared transport stays below every camera in grid and focus modes.
  await page.reload(); await page.getByRole("button",{name:"Pause playback",exact:true}).click();
  assert.equal(await page.locator(".demo-person i").count(),0);
  assert.equal(await page.locator(".monitor-side-panel .view-settings").count(),0);
  await page.getByRole("img",{name:"Illustrative audio waveform, generated for this demo",exact:true}).waitFor();
  await page.locator(".audio-waveform canvas").first().waitFor({state:"attached"});
  assert.equal(await page.locator(".overview-handle").first().evaluate(e=>e.getBoundingClientRect().width),6);
  await page.getByRole("tab",{name:"Overview",exact:true}).focus(); await page.keyboard.press("ArrowRight");
  assert.equal(await page.getByRole("tab",{name:"Grid",exact:true}).getAttribute("aria-selected"),"true");

  assert.equal(await page.evaluate(()=>getComputedStyle(document.documentElement).getPropertyValue("--primary").trim()),"#20818E");
  for (const mode of ["Grid", "Focus", "Single"]) {
    if (mode === "Focus") { await page.locator(".play-button").focus(); await page.keyboard.press("3"); }
    else await page.getByRole("tab",{name:mode === "Single" ? "Overview" : mode,exact:true}).click();
    const grid=await page.locator(".camera-layout").boundingBox(); const bar=await page.locator(".playback").boundingBox();
    assert.ok(bar.y >= grid.y + grid.height - 1,`${mode}: timeline below camera grid`);
    assert.ok(Math.abs(bar.width-grid.width)<3,`${mode}: timeline spans grid width`);
    if (mode === "Grid") await page.screenshot({path:"docs/ui-after/grid-1024x768.png"});
  }
  assert.equal(await page.locator(".timeline-fit, .timeline-zoom, .timeline-recorded-range").count(),0);
  assert.equal(await page.locator(".timeline-overview-row").evaluate(e=>e.getBoundingClientRect().height),12);
  assert.equal(await page.locator(".editor-playhead").evaluate(e=>getComputedStyle(e).width),"1px");
  assert.equal(await page.locator(".editor-incident").first().evaluate(e=>getComputedStyle(e).getPropertyValue("--incident-color").trim()),"#20818E");
  // Component harness verifies a one-hour recording defaults to 30 minutes,
  // and that a live recording keeps its zoom while its elapsed time grows.
  await page.evaluate(async()=>{
    const ReactModule=await import("/node_modules/.vite/deps/react.js");const React=ReactModule.default??ReactModule;
    const DOM=await import("/node_modules/.vite/deps/react-dom_client.js");const {default:Timeline}=await import("/src/EditorTimeline.tsx");
    const host=document.createElement("div");host.id="timeline-fixture";host.style.cssText="position:fixed;inset:100px 20px auto;z-index:100;background:#222";document.body.append(host);
    const root=(DOM.default??DOM).createRoot(host);
    window.timelineHarness=(duration,live)=>root.render(React.createElement(Timeline,{camera:"Test recording",room:0,duration,position:0,playing:false,demo:false,peaks:null,video:{current:null},markers:[],live,onSeek:()=>{}}));
    window.timelineHarness(3600,false);
  });
  const harness=page.locator("#timeline-fixture");
  await page.waitForFunction(()=>document.querySelector("#timeline-fixture .timeline-content")?.style.width==="200%");
  await harness.getByRole("button",{name:"Visible timeline end"}).focus(); await page.keyboard.press("End");
  assert.equal(await harness.locator(".timeline-content").evaluate(e=>e.style.width),"100%");
  await page.evaluate(()=>window.timelineHarness(95,true));
  await page.waitForFunction(()=>document.querySelector("#timeline-fixture .editor-scrubber")?.max === "95");
  assert.equal(await harness.getByRole("slider").isDisabled(),true);
  await harness.getByRole("button",{name:"Visible timeline end"}).focus(); await page.keyboard.press("ArrowLeft");
  await page.evaluate(()=>window.timelineHarness(96,true));
  await page.waitForFunction(()=>document.querySelector("#timeline-fixture .editor-scrubber")?.max === "96");
  assert.ok(await harness.locator(".timeline-content").evaluate(e=>parseFloat(e.style.width))>100);
  await harness.getByRole("button",{name:"Visible timeline end"}).focus(); await page.keyboard.press("End");
  await page.evaluate(()=>document.getElementById("timeline-fixture").remove());
  // Test the clip download boundary with an explicit transport fixture, not real footage.
  const bytes = Buffer.from([0x1a,0x45,0xdf,0xa3,0,1,2,3]);
  await page.route("**/test-evidence.webm", route => route.fulfill({contentType:"video/webm",body:bytes}));
  await page.evaluate(async () => {
    const React = await import("/node_modules/.vite/deps/react.js"); const ReactDOM = await import("/node_modules/.vite/deps/react-dom_client.js"); const createRoot = (ReactDOM.default ?? ReactDOM).createRoot; const {default: EventExport} = await import("/src/EventExport.tsx");
    const host = document.createElement("div"); host.id="export-fixture"; host.style.cssText="position:fixed;inset:100px 0 auto;z-index:100;background:#222"; document.body.append(host);
    createRoot(host).render((React.default ?? React).createElement(EventExport,{cameraId:"test-camera",userId:"test-user",incident:{id:"transport-fixture",title:"Export transport fixture",kind:"test",room:"test",status:"resolved",origin:"fixture",priority:"low",opened_at:new Date().toISOString(),observations:[],clip_url:"/test-evidence.webm",media_time_ms:1000,media_end_time_ms:2000}}));
  });
  await page.locator("#export-fixture").getByRole("button",{name:"Export clip",exact:true}).click();
  await page.getByRole("textbox",{name:"Reason for export"}).fill("Test clip download");
  const clipDownload=page.waitForEvent("download"); await page.getByRole("button",{name:"Download",exact:true}).click();
  assert.deepEqual(await readFile(await (await clipDownload).path()),bytes);
  assert.deepEqual(errors, []);
  console.log("Review UI passed: video-contained timeline, full-height sidebar, top-aligned collapsed sections, transport, shortcuts menu, event details/clip downloads, and three viewport screenshots.");
} finally { await browser.close(); }

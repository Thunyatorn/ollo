import { mkdir } from "node:fs/promises";
import { chromium } from "playwright";
const phase = process.argv[2] || "current";
if (!/^[a-z0-9-]+$/.test(phase)) throw new Error("Invalid phase name");
const browser = await chromium.launch({headless:true});
try {
  const page=await browser.newPage();
  await mkdir(`docs/ui-round2/${phase}`,{recursive:true});
  for(const [width,height] of [[1323,820],[1920,1200],[1024,768]]){
    await page.setViewportSize({width,height});await page.goto(process.env.LOOKOUT_URL || "http://127.0.0.1:5175/");
    await page.getByRole("button",{name:"Pause playback",exact:true}).click();
    await page.screenshot({path:`docs/ui-round2/${phase}/${width}x${height}.png`});
    const track=await page.locator(".editor-track").boundingBox();
    if(track.y+track.height>height)throw Error(`${phase}: timeline clipped at ${width}x${height}`);
  }
  console.log(`${phase}: three screenshots captured; timeline fits.`);
} finally {await browser.close();}

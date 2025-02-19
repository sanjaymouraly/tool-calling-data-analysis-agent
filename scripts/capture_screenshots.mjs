/**
 * Capture real screenshots of the running application.
 *
 * Usage:
 *   node scripts/capture_screenshots.mjs [baseUrl] [outputDir]
 *
 * The script drives the *production* build through the browser, so the
 * images in docs/images are genuine screenshots of the shipped UI.
 */
import { chromium } from 'playwright'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'

const baseUrl = process.argv[2] ?? 'http://localhost:8000'
const outputDir = process.argv[3] ?? 'docs/images'
const viewport = { width: 1440, height: 960 }

await mkdir(outputDir, { recursive: true })

const browser = await chromium.launch()
const context = await browser.newContext({ viewport, deviceScaleFactor: 2 })
const page = await context.newPage()

const consoleErrors = []
page.on('console', (message) => {
  if (message.type() === 'error') consoleErrors.push(message.text())
})
page.on('pageerror', (error) => consoleErrors.push(`pageerror: ${error.message}`))

async function shot(name, { full = false } = {}) {
  await page.waitForTimeout(500)
  const file = path.join(outputDir, `${name}.png`)
  await page.screenshot({ path: file, fullPage: full })
  console.log(`captured ${file}`)
}

async function goto(route) {
  await page.goto(`${baseUrl}${route}`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(400)
}

console.log(`capturing from ${baseUrl}`)

await goto('/')
await shot('dashboard')

await goto('/datasets')
await shot('datasets')

// Dataset detail: find the first dataset link and open it.
const firstDataset = page.locator('a[href^="/datasets/"]').first()
if (await firstDataset.count()) {
  await firstDataset.click()
  await page.waitForLoadState('networkidle')
  await page.waitForTimeout(700)
  await shot('schema')

  const qualityTab = page.getByRole('tab', { name: /data quality/i })
  if (await qualityTab.count()) {
    await qualityTab.click()
    await page.waitForTimeout(500)
    await shot('data-quality')
  }

  const previewTab = page.getByRole('tab', { name: /preview/i })
  if (await previewTab.count()) {
    await previewTab.click()
    await page.waitForTimeout(500)
    await shot('preview')
  }
}

// Workspace with a real answer + evidence panel.
await goto('/workspace')
const demoQuestion = 'What were monthly sales and growth rates?'
const questionBox = page.locator('#question')
if (await questionBox.count()) {
  // Authorise exactly the retail orders dataset: deselect everything else.
  const chips = page.locator('button[aria-pressed]')
  const chipCount = await chips.count()
  for (let index = 0; index < chipCount; index += 1) {
    const chip = chips.nth(index)
    const name = (await chip.innerText()).trim()
    const pressed = await chip.getAttribute('aria-pressed')
    if (name.startsWith('Retail Orders') && pressed === 'false') {
      await chip.click()
    } else if (!name.startsWith('Retail Orders') && pressed === 'true') {
      await chip.click()
    }
  }
  await questionBox.fill(demoQuestion)
  await page.getByRole('button', { name: /^Ask$/ }).click()
  await page.waitForSelector('text=Evidence-backed answer', { timeout: 60000 })
  await page.waitForTimeout(1500)
  await page.evaluate(() => window.scrollTo({ top: 0 }))
  await page.waitForTimeout(400)
  await shot('workspace')

  const answerCard = page.getByText('Evidence-backed answer').first()
  if (await answerCard.count()) {
    await answerCard.scrollIntoViewIfNeeded()
    await page.waitForTimeout(600)
    await shot('workspace-answer')
  }

  const chartsHeading = page.getByText('Visualisations').first()
  if (await chartsHeading.count()) {
    await chartsHeading.scrollIntoViewIfNeeded()
    await page.waitForTimeout(900)
    await shot('charts')
  }

  const evidenceTab = page.getByRole('button', { name: /How this was calculated/i })
  if (await evidenceTab.count()) {
    await evidenceTab.click()
    await page.waitForTimeout(900)
    await page.getByText('Source data').first().scrollIntoViewIfNeeded()
    await page.waitForTimeout(500)
    await shot('evidence')
  }

  const traceTab = page.getByRole('button', { name: /Tool trace/i })
  if (await traceTab.count()) {
    await traceTab.click()
    await page.waitForTimeout(700)
    await traceTab.scrollIntoViewIfNeeded()
    await page.waitForTimeout(400)
    await shot('tool-trace')
  }
}

await goto('/builder')
await shot('builder')

await goto('/history')
await shot('history')

await goto('/settings')
await shot('settings')

// Dark theme
await goto('/')
await page.getByRole('button', { name: /switch to dark theme/i }).click()
await page.waitForTimeout(700)
await shot('dashboard-dark')

await browser.close()

if (consoleErrors.length) {
  console.error('\nBrowser console errors detected:')
  for (const error of consoleErrors) console.error(` - ${error}`)
  process.exitCode = 1
} else {
  console.log('\nNo browser console errors.')
}

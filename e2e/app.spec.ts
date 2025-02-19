import { expect, test } from '@playwright/test'

test.describe('Tool-Calling Data Analysis Agent', () => {
  test('the overview page loads with the demo datasets', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (error) => errors.push(error.message))

    await page.goto('/')
    await expect(page.getByRole('heading', { name: 'Overview' })).toBeVisible()
    await expect(page.getByText('Ready-to-run questions')).toBeVisible()
    await expect(page.getByRole('link', { name: /What were monthly sales/ }).first()).toBeVisible()
    expect(errors).toEqual([])
  })

  test('the dataset manager lists the synthetic demo data', async ({ page }) => {
    await page.goto('/datasets')
    await expect(page.getByRole('heading', { name: 'Dataset manager' })).toBeVisible()
    await expect(page.getByText('Retail Orders').first()).toBeVisible()
    await expect(page.getByText('Supplier Deliveries').first()).toBeVisible()
  })

  test('a dataset exposes its schema, preview and quality report', async ({ page }) => {
    await page.goto('/datasets')
    await page.getByRole('link', { name: 'Retail Orders' }).first().click()
    await expect(page.getByRole('heading', { name: /Retail Orders/ })).toBeVisible()

    await page.getByRole('tab', { name: /Schema/ }).click()
    await expect(page.getByRole('cell', { name: 'Revenue' }).first()).toBeVisible()

    await page.getByRole('tab', { name: /Data quality/ }).click()
    await expect(page.getByText('Quality score')).toBeVisible()
  })

  test('the workspace answers a question with evidence', async ({ page }) => {
    await page.goto('/workspace')

    // Authorise exactly the retail orders dataset.
    const chips = page.locator('button[aria-pressed]')
    const count = await chips.count()
    for (let index = 0; index < count; index += 1) {
      const chip = chips.nth(index)
      const name = (await chip.innerText()).trim()
      const pressed = await chip.getAttribute('aria-pressed')
      if (name.startsWith('Retail Orders') && pressed === 'false') await chip.click()
      else if (!name.startsWith('Retail Orders') && pressed === 'true') await chip.click()
    }

    await page.getByLabel('Question').fill('What were monthly sales and growth rates?')
    await page.getByRole('button', { name: /^Ask$/ }).click()

    await expect(page.getByText('Evidence-backed answer')).toBeVisible({ timeout: 60_000 })
    await expect(page.getByRole('heading', { name: 'Evidence' }).first()).toBeVisible()

    // The evidence panel must expose the dataset hash and the formulas.
    await page.getByRole('button', { name: /How this was calculated/ }).click()
    await expect(page.getByText('Source data')).toBeVisible()
    await expect(page.getByText('SHA-256')).toBeVisible()

    // The tool trace must only contain allowlisted tools.
    await page.getByRole('button', { name: /Tool trace/ }).click()
    await expect(page.getByText('time_series').first()).toBeVisible()
  })

  test('the visual query builder runs a deterministic aggregation', async ({ page }) => {
    await page.goto('/builder')
    await expect(page.getByRole('heading', { name: 'Visual query builder' })).toBeVisible()
    const measure = page.getByLabel('Measure (numeric column)')
    await expect(measure).not.toHaveValue('')
    await page.getByRole('button', { name: 'Run query' }).click()
    await expect(page.getByText(/row\(s\) returned/)).toBeVisible({ timeout: 30_000 })
  })

  test('the settings page lists the providers without exposing secrets', async ({ page }) => {
    await page.goto('/settings')
    await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible()
    await expect(page.getByText('Provider wizard')).toBeVisible()
    await expect(page.getByLabel('Provider')).toContainText('Anthropic Claude API')
    await expect(page.getByLabel('Provider')).toContainText('Ollama (local)')
    await expect(page.getByText('Configured providers')).toBeVisible()
    await expect(page.getByText('Security model')).toBeVisible()
  })

  test('the dark theme can be toggled', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: /switch to dark theme/i }).click()
    await expect(page.locator('html')).toHaveClass(/dark/)
  })

  test('the history page shows persisted analyses', async ({ page }) => {
    await page.goto('/workspace')
    const chips = page.locator('button[aria-pressed]')
    const count = await chips.count()
    for (let index = 0; index < count; index += 1) {
      const chip = chips.nth(index)
      const name = (await chip.innerText()).trim()
      const pressed = await chip.getAttribute('aria-pressed')
      if (name.startsWith('Retail Orders') && pressed === 'false') await chip.click()
      else if (!name.startsWith('Retail Orders') && pressed === 'true') await chip.click()
    }
    await page.getByLabel('Question').fill('What was total revenue?')
    await page.getByRole('button', { name: /^Ask$/ }).click()
    await expect(page.getByText('Evidence-backed answer')).toBeVisible({ timeout: 60_000 })

    await page.goto('/history')
    await expect(page.getByText('What was total revenue?').first()).toBeVisible()
  })

  test('an unknown route shows the not-found page', async ({ page }) => {
    await page.goto('/this-route-does-not-exist')
    await expect(page.getByText('Page not found')).toBeVisible()
  })
})

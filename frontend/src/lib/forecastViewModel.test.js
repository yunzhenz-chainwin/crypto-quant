import test from 'node:test'
import assert from 'node:assert/strict'

import { normalizeForecast, stateOfForecast } from './forecastViewModel.js'

function readyPayload(overrides = {}) {
  return {
    status: 'ready',
    horizon_days: 5,
    probabilities: { up: 0.6, down: 0.4 },
    confidence: { score: 60, threshold: 40 },
    evidence: { schema_version: 2, items: [] },
    ...overrides,
  }
}

test('failed release gate always prevents a ready UI state', () => {
  const forecast = normalizeForecast(readyPayload({
    evidence: {
      schema_version: 2,
      items: [{
        code: 'manual_gate',
        label: '人工門檻未通過',
        status: 'failed',
        source_bucket: 'opposing',
        category: 'release_gate',
        polarity: 'neutral',
      }],
    },
  }), 5)

  assert.equal(stateOfForecast(forecast).kind, 'abstain')
})

test('confidence below threshold is synthesized as a failed release gate', () => {
  const forecast = normalizeForecast(readyPayload({
    confidence: { score: 30, threshold: 40 },
  }), 5)

  assert.equal(
    forecast.releaseGates.find(item => item.code === 'confidence_release_threshold')?.status,
    'failed',
  )
  assert.equal(stateOfForecast(forecast).kind, 'abstain')
})

test('missing directional probability fails closed', () => {
  const forecast = normalizeForecast(readyPayload({
    probabilities: { up: 0.6 },
  }), 5)

  assert.equal(
    forecast.releaseGates.some(item => item.code === 'missing_directional_probabilities'),
    true,
  )
  assert.equal(stateOfForecast(forecast).kind, 'abstain')
})

test('legacy nested decimal quantiles are converted to percentage points', () => {
  const forecast = normalizeForecast(readyPayload({
    return_quantiles: { q10: -0.1, q50: 0.02, q90: 0.2 },
  }), 5)

  assert.deepEqual([forecast.q10, forecast.q50, forecast.q90], [-10, 2, 20])
})

test('nested pct quantiles stay in percentage points', () => {
  const forecast = normalizeForecast(readyPayload({
    return_quantiles: { q10: -10, q50: 2, q90: 20 },
    return_quantiles_unit: 'pct',
  }), 5)

  assert.deepEqual([forecast.q10, forecast.q50, forecast.q90], [-10, 2, 20])
})

test('legacy evidence keeps its original source bucket without text classification', () => {
  const forecast = normalizeForecast(readyPayload({
    evidence: {
      for: ['文字提到下跌風險，但來源仍是 supporting'],
      against: ['文字提到上漲，但來源仍是 opposing'],
    },
  }), 5)

  assert.equal(forecast.supportingEvidence[0].sourceBucket, 'supporting')
  assert.equal(forecast.supportingEvidence[0].polarity, 'neutral')
  assert.equal(forecast.opposingEvidence[0].sourceBucket, 'opposing')
  assert.equal(forecast.opposingEvidence[0].polarity, 'neutral')
})

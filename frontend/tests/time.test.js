import test from 'node:test'
import assert from 'node:assert/strict'
import { dateTime } from '../src/format.js'

test('UTC and UTC+8 representations display the same Beijing time', () => {
  assert.equal(dateTime('2026-11-09T08:00:00Z'), '2026-11-09 16:00:00 UTC+8')
  assert.equal(dateTime('2026-11-09T08:00:00Z'), dateTime('2026-11-09T16:00:00+08:00'))
  assert.equal(dateTime('2026-11-09T20:00:00Z'), '2026-11-10 04:00:00 UTC+8')
})

test('missing, invalid and timezone-less times are not guessed', () => {
  for (const value of [null, '', 'not-a-date', '2026-11-09T08:00:00']) assert.equal(dateTime(value), '—')
})

test('browser timezone does not affect business display', () => {
  const original = process.env.TZ
  try {
    for (const zone of ['UTC', 'America/Los_Angeles', 'Asia/Tokyo']) {
      process.env.TZ = zone
      assert.equal(dateTime('2026-11-09T08:00:00Z'), '2026-11-09 16:00:00 UTC+8')
    }
  } finally { if (original === undefined) delete process.env.TZ; else process.env.TZ = original }
})

import { describe, expect, it, vi } from 'vitest'
import { ApiError, api } from './client'

function stubFetch(response: Response) {
  // A Response body can be read once; hand out a fresh copy per call.
  const fetchMock = vi.fn(async () => response.clone())
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('api()', () => {
  it('sends the CSRF header on writes but not on reads', async () => {
    const fetchMock = stubFetch(new Response('{}'))
    await api('/accounts')
    await api('/accounts', { method: 'POST', body: { name: 'x' } })

    const [, readInit] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    const [url, writeInit] = fetchMock.mock.calls[1] as unknown as [string, RequestInit]
    expect(readInit.headers).not.toHaveProperty('X-Finboard-Client')
    expect(url).toBe('/api/v1/accounts')
    expect(writeInit.headers).toMatchObject({
      'X-Finboard-Client': '1',
      'Content-Type': 'application/json',
    })
    expect(writeInit.body).toBe('{"name":"x"}')
  })

  it('turns problem+json into an ApiError', async () => {
    stubFetch(
      new Response(
        JSON.stringify({ status: 409, code: 'conflict', title: 'Conflict', detail: 'Name taken' }),
        { status: 409 },
      ),
    )
    const error = await api('/accounts', { method: 'POST', body: {} }).catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 409, code: 'conflict', message: 'Name taken' })
  })

  it('exposes the first field validation message', async () => {
    stubFetch(
      new Response(
        JSON.stringify({
          status: 422,
          code: 'invalid_request',
          title: 'Invalid request',
          errors: [
            { loc: ['body', 'masked_number'], msg: 'String should match pattern', type: 'x' },
          ],
        }),
        { status: 422 },
      ),
    )
    const error = (await api('/accounts').catch((e: unknown) => e)) as ApiError
    expect(error.fieldMessage).toBe('String should match pattern')
  })

  it('returns undefined for 204', async () => {
    stubFetch(new Response(null, { status: 204 }))
    await expect(api('/accounts/1', { method: 'DELETE' })).resolves.toBeUndefined()
  })
})

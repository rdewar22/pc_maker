import { useEffect, useState } from 'react'

const RESOLUTIONS = ['1080p', '1440p', '4k']
const SETTINGS = [
  { id: 'low', label: 'Low' },
  { id: 'medium', label: 'Medium' },
  { id: 'high', label: 'High' },
  { id: 'ultra', label: 'Ultra' },
]
const FPS_OPTIONS = [60, 120, 144, 165, 240]

const SLOT_LABELS = {
  gpu: 'GPU',
  cpu: 'CPU',
  motherboard: 'Motherboard',
  ram: 'Memory',
  storage: 'Storage',
  psu: 'Power Supply',
  case: 'Case',
  cooler: 'CPU Cooler',
}

const VARIANT_INFO = {
  value: { label: 'Value', desc: 'Cheapest build that hits your target' },
  balanced: { label: 'Balanced', desc: 'One step up for comfort and longevity' },
  headroom: { label: 'Headroom', desc: 'Extra GPU/CPU margin for the future' },
}

function formatUsd(n) {
  return n == null ? '—' : `$${Math.round(n).toLocaleString()}`
}

async function api(path, opts) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `Request failed (${res.status})`)
  }
  return res.json()
}

export default function App() {
  const [games, setGames] = useState([])
  const [gameId, setGameId] = useState('')
  const [resolution, setResolution] = useState('1080p')
  const [settings, setSettings] = useState('high')
  const [targetFps, setTargetFps] = useState(60)
  const [budget, setBudget] = useState('')
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    api('/api/games')
      .then((d) => {
        setGames(d.games)
        if (d.games.length) setGameId(d.games[0].id)
      })
      .catch((e) => setError(e.message))
  }, [])

  async function onSubmit(e) {
    e.preventDefault()
    setError('')
    setResult(null)
    setLoading(true)
    try {
      const body = { game_id: gameId, resolution, settings, target_fps: targetFps }
      const b = parseFloat(budget)
      if (!Number.isNaN(b) && b > 0) body.budget_usd = b
      setResult(await api('/api/builds', { method: 'POST', body: JSON.stringify(body) }))
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const game = games.find((g) => g.id === gameId)

  return (
    <main>
      <header>
        <h1>PC Maker</h1>
        <p className="tagline">Tell us the game. We&apos;ll tell you the PC.</p>
      </header>

      <form className="picker" onSubmit={onSubmit}>
        <label className="field field-game">
          <span>Game</span>
          <select value={gameId} onChange={(e) => setGameId(e.target.value)}>
            {games.map((g) => (
              <option key={g.id} value={g.id}>
                {g.name}
                {g.fps_cap ? ` (capped at ${g.fps_cap} FPS)` : ''}
              </option>
            ))}
          </select>
        </label>

        <div className="field">
          <span>Resolution</span>
          <div className="segmented">
            {RESOLUTIONS.map((r) => (
              <button
                key={r}
                type="button"
                className={resolution === r ? 'on' : ''}
                onClick={() => setResolution(r)}
              >
                {r}
              </button>
            ))}
          </div>
        </div>

        <div className="field">
          <span>Settings</span>
          <div className="segmented">
            {SETTINGS.map((s) => (
              <button
                key={s.id}
                type="button"
                className={settings === s.id ? 'on' : ''}
                onClick={() => setSettings(s.id)}
              >
                {s.label}
              </button>
            ))}
          </div>
        </div>

        <div className="field">
          <span>Target FPS</span>
          <div className="segmented">
            {FPS_OPTIONS.map((f) => (
              <button
                key={f}
                type="button"
                className={targetFps === f ? 'on' : ''}
                disabled={game?.fps_cap && f > game.fps_cap}
                onClick={() => setTargetFps(f)}
              >
                {f}
              </button>
            ))}
          </div>
        </div>

        <label className="field field-budget">
          <span>Budget (optional)</span>
          <input
            type="number"
            min="0"
            placeholder="e.g. 1200"
            value={budget}
            onChange={(e) => setBudget(e.target.value)}
          />
        </label>

        <button className="go" type="submit" disabled={loading || !gameId}>
          {loading ? 'Building…' : 'Find my build'}
        </button>
      </form>

      {error && <div className="error">{error}</div>}

      {result && (
        <section className="results">
          <h2>
            {result.game.name} — {result.resolution} / {result.settings} / target{' '}
            {result.target_fps} FPS
          </h2>
          {result.notes?.map((n, i) => (
            <p key={i} className="note">
              {n}
            </p>
          ))}
          <div className="builds">
            {result.builds.map((b) => (
              <BuildCard key={b.variant} build={b} />
            ))}
          </div>
          {result.prebuilts?.length > 0 && (
            <div className="prebuilts">
              <h3>
                Or buy a prebuilt{' '}
                <span className="muted">
                  — ready to ship, links go to live listings
                </span>
              </h3>
              {result.prebuilts.map((pb) => (
                <a
                  key={pb.id}
                  className="prebuilt-row"
                  href={pb.retail_urls?.bestbuy}
                  target="_blank"
                  rel="noreferrer"
                >
                  <span className="pb-name">{pb.name}</span>
                  <span className="pb-specs">
                    {pb.ram_gb}GB RAM · {pb.storage_gb >= 1000 ? `${pb.storage_gb / 1000}TB` : `${pb.storage_gb}GB`}
                  </span>
                  <span className="pb-fps">~{pb.estimated_fps} FPS</span>
                  <span className="pb-price">{formatUsd(pb.price_usd)} ↗</span>
                </a>
              ))}
              <a
                className="prebuilt-all"
                href={`https://www.bestbuy.com/site/searchpage.jsp?st=${encodeURIComponent(
                  'gaming PC ' + (result.game.name || ''),
                )}`}
                target="_blank"
                rel="noreferrer"
              >
                Browse more prebuilts at Best Buy ↗
              </a>
            </div>
          )}
          <p className="note pricing-note">
            FPS figures are model estimates (±15–20%), and prices marked as baseline
            are curated snapshots — always check the linked retailer page for live
            pricing and stock.
          </p>
        </section>
      )}
    </main>
  )
}

function partLink(part) {
  if (part.live?.buy_url) return part.live.buy_url
  return part.retail_urls?.bestbuy || null
}

function BuildCard({ build }) {
  const [open, setOpen] = useState(build.variant === 'value')
  const info = VARIANT_INFO[build.variant] ?? { label: build.variant, desc: '' }
  const parts = Object.entries(build.parts).filter(([, p]) => p)

  return (
    <article className={`card card-${build.variant}`}>
      <header onClick={() => setOpen(!open)} className="card-head">
        <div>
          <h3>{info.label}</h3>
          <p className="desc">{info.desc}</p>
        </div>
        <div className="card-stats">
          <span className="fps">~{build.estimated_fps} FPS</span>
          <span className="price">{formatUsd(build.total_price_usd)}</span>
          <span className="chevron">{open ? '▾' : '▸'}</span>
        </div>
      </header>
      {open && (
        <table>
          <tbody>
            {parts.map(([slot, part]) => {
              const url = partLink(part)
              return (
                <tr key={slot}>
                  <th>{SLOT_LABELS[slot] ?? slot}</th>
                  <td>
                    {url ? (
                      <a href={url} target="_blank" rel="noreferrer">
                        {part.name} ↗
                      </a>
                    ) : (
                      part.name
                    )}
                    {part.live?.in_stock === false && (
                      <span className="oos">out of stock</span>
                    )}
                  </td>
                  <td className="right">{formatUsd(part.effective_price_usd)}</td>
                </tr>
              )
            })}
            <tr className="total">
              <th>Total</th>
              <td className="right" colSpan={2}>
                {formatUsd(build.total_price_usd)}
              </td>
            </tr>
          </tbody>
        </table>
      )}
      {build.compatibility_errors?.length > 0 && (
        <ul className="compat-errors">
          {build.compatibility_errors.map((e, i) => (
            <li key={i}>{e}</li>
          ))}
        </ul>
      )}
    </article>
  )
}

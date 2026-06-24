import { useEffect, useState } from 'react'
import { Minus, Square, X } from 'lucide-react'
import { Window } from '@wailsio/runtime'

function WindowControls() {
  const [maximised, setMaximised] = useState(false)

  async function syncMaximised() {
    try {
      setMaximised(await Window.IsMaximised())
    } catch {
      setMaximised(false)
    }
  }

  async function toggleMaximise() {
    try {
      if (await Window.IsMaximised()) {
        await Window.Restore()
      } else {
        await Window.Maximise()
      }
      await syncMaximised()
    } catch {
      return
    }
  }

  async function minimise() {
    try {
      await Window.Minimise()
    } catch {
      return
    }
  }

  async function close() {
    try {
      await Window.Close()
    } catch {
      return
    }
  }

  useEffect(() => {
    void syncMaximised()
  }, [])

  return (
    <div className="window-controls no-drag">
      <button className="window-button" title="最小化" type="button" onClick={minimise}>
        <Minus size={15} />
      </button>
      <button className="window-button" title={maximised ? '还原' : '最大化'} type="button" onClick={toggleMaximise}>
        <Square size={13} />
      </button>
      <button className="window-button window-button-close" title="关闭" type="button" onClick={close}>
        <X size={16} />
      </button>
    </div>
  )
}

export default WindowControls

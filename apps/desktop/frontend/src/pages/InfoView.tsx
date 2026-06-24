import { Eye, FolderOpen, Save } from 'lucide-react'
import { Button } from 'react-windows-ui'
import SettingField from '../components/SettingField'
import type { PageMetric, ReverseFillRow, SettingsGroup } from '../types'

interface InfoViewProps {
  title: string
  items?: string[]
  metrics?: PageMetric[]
  reverseFill?: ReverseFillRow[]
  settings?: SettingsGroup[]
  reverseFillPath?: string
  busy?: boolean
  onSettingChange?: (id: string, value: string | boolean) => void
  onChooseReverseFill?: () => void
  onPreviewReverseFill?: () => void
  onSaveSettings?: () => void
}

function InfoView({
  title,
  items,
  metrics,
  reverseFill,
  settings,
  reverseFillPath,
  busy = false,
  onSettingChange,
  onChooseReverseFill,
  onPreviewReverseFill,
  onSaveSettings,
}: InfoViewProps) {
  return (
    <section className="page scroll-page">
      <div className="content-stack">
        <section className="surface info-panel">
          <div className="section-heading">
            <h2>{title}</h2>
          </div>

          {reverseFill ? (
            <div className="toolbar-row">
              <Button value="选择 Excel" icon={<FolderOpen size={15} />} onClick={onChooseReverseFill} />
              <Button value="预览反填" icon={<Eye size={15} />} disabled={busy || !reverseFillPath} onClick={onPreviewReverseFill} />
              <span>{reverseFillPath || '未选择文件'}</span>
            </div>
          ) : null}

          {items?.length ? (
            <div className="info-list">
              {items.map((item) => <span key={item}>{item}</span>)}
            </div>
          ) : null}

          {metrics?.length ? (
            <div className="metric-grid">
              {metrics.map((metric) => (
                <div key={metric.label} className="metric-tile">
                  <span>{metric.label}</span>
                  <strong>{metric.value}</strong>
                </div>
              ))}
            </div>
          ) : null}

          {reverseFill?.length ? (
            <div className="reverse-list">
              {reverseFill.map((row) => (
                <div key={`${row.question}-${row.column}`}>
                  <span>{row.question}</span>
                  <small>{row.column}</small>
                  <strong>{row.state}</strong>
                </div>
              ))}
            </div>
          ) : null}
        </section>

        {settings?.map((group) => (
          <section className="surface settings-panel" key={group.title}>
            <div className="section-heading">
              <h2>{group.title}</h2>
            </div>
            {group.fields.map((field) => (
              <SettingField
                key={field.id}
                field={field}
                onChange={(id, value) => onSettingChange?.(id, value)}
              />
            ))}
          </section>
        ))}

        {settings?.length ? (
          <div className="footer-actions">
            <Button type="primary" value="保存设置" icon={<Save size={15} />} disabled={busy} onClick={onSaveSettings} />
          </div>
        ) : null}
      </div>
    </section>
  )
}

export default InfoView

import SettingField from '../components/SettingField'
import type { SettingsGroup } from '../types'

interface RuntimeViewProps {
  groups: SettingsGroup[]
  onFieldChange: (id: string, value: string | boolean) => void
}

function RuntimeView({ groups, onFieldChange }: RuntimeViewProps) {
  return (
    <section className="page scroll-page">
      <div className="content-stack">
        {groups.map((group) => (
          <section className="surface settings-panel" key={group.title}>
            <div className="section-heading">
              <h2>{group.title}</h2>
            </div>
            {group.fields.map((field) => (
              <SettingField key={field.id} field={field} onChange={onFieldChange} />
            ))}
          </section>
        ))}
      </div>
    </section>
  )
}

export default RuntimeView

import { useMemo, type ChangeEvent, type ReactElement } from 'react'
import { InputText, SelectNative, Switch } from 'react-windows-ui'
import type { SettingField as SettingFieldType } from '../types'

interface SettingFieldProps {
  field: SettingFieldType
  onChange: (id: string, value: string | boolean) => void
}

const SelectControl = SelectNative as unknown as (props: {
  data: Array<{ label: string, value: string }>
  value?: string
  disabled?: boolean
  onChange?: (event: ChangeEvent<HTMLSelectElement>) => void
}) => ReactElement

function SettingField({ field, onChange }: SettingFieldProps) {
  const options = useMemo(
    () => (field.options?.length ? field.options : [field.value]).map((option) => ({ label: option, value: option })),
    [field.options, field.value],
  )

  return (
    <div className="setting-row">
      <div className="setting-copy">
        <span>{field.label}</span>
        {field.description ? <small>{field.description}</small> : null}
      </div>

      {field.kind === 'toggle' ? (
        <Switch
          key={`${field.id}-${field.value}`}
          label
          labelOn="开"
          labelOff="关"
          defaultChecked={field.value === 'true'}
          onChange={() => onChange(field.id, field.value !== 'true')}
        />
      ) : null}

      {field.kind === 'select' ? (
        <SelectControl
          data={options}
          value={field.value}
          onChange={(event) => onChange(field.id, event.target.value)}
        />
      ) : null}

      {field.kind === 'number' ? (
        <InputText
          value={field.value}
          width="8rem"
          onChange={(event: ChangeEvent<HTMLInputElement>) => onChange(field.id, event.target.value)}
        />
      ) : null}

      {field.kind === 'text' ? (
        <InputText
          value={field.value}
          width="18rem"
          onChange={(event: ChangeEvent<HTMLInputElement>) => onChange(field.id, event.target.value)}
        />
      ) : null}

      {!['toggle', 'select', 'number', 'text'].includes(field.kind) ? (
        <span className="readonly-value">{field.value}</span>
      ) : null}
    </div>
  )
}

export default SettingField

import { type ReactElement } from 'react'
import { Button, TableView } from 'react-windows-ui'
import type { StrategyRule } from '../types'

interface StrategyViewProps {
  rules: StrategyRule[]
  dimensions: string[]
}

const TableControl = TableView as unknown as (props: {
  columns: Array<{ title: string, sortable?: boolean, showSortIcon?: boolean }>
  rows: string[][]
  rowFontSize?: number
  headerFontSize?: number
}) => ReactElement

function StrategyView({ rules, dimensions }: StrategyViewProps) {
  return (
    <section className="page strategy-page">
      <aside className="surface dimension-panel">
        <div className="section-heading">
          <h2>维度</h2>
          <span>{dimensions.length}</span>
        </div>
        <div className="dimension-list">
          {dimensions.map((item) => <Button key={item} value={item} />)}
        </div>
      </aside>

      <section className="surface table-panel">
        <div className="section-heading">
          <h2>逻辑规则</h2>
          <span>{rules.length}</span>
        </div>
        <TableControl
          columns={[
            { title: '条件', showSortIcon: false },
            { title: '动作', showSortIcon: false },
            { title: '目标', showSortIcon: false },
          ]}
          rows={rules.map((rule) => [rule.condition, rule.action, rule.target])}
          rowFontSize={13}
          headerFontSize={13}
        />
      </section>
    </section>
  )
}

export default StrategyView

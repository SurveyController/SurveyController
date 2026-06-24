import { type ChangeEvent, type ReactElement } from 'react'
import {
  Brush,
  FilePlus2,
  List,
  Play,
  QrCode,
  Save,
  SlidersHorizontal,
  Square,
  Trash2,
} from 'lucide-react'
import { Button, ButtonGroup, InputText, ProgressBar, SelectNative, SliderBar, Switch, TableView } from 'react-windows-ui'
import type { DashboardState } from '../types'

interface DashboardViewProps {
  dashboard: DashboardState
  logs: string[]
  busy?: boolean
  onUpdateUrl: (value: string) => void
  onAutoConfig: () => void
  onLoadConfig: () => void
  onSaveConfig: () => void
  onOpenRuntime: () => void
  onTargetChange: (value: number) => void
  onThreadsChange: (value: number) => void
  onRandomIpChange: (value: boolean) => void
  onProxySourceChange: (value: string) => void
  onRun: () => void
  onCancelRun: () => void
}

const SelectControl = SelectNative as unknown as (props: {
  data: Array<{ label: string, value: string }>
  value?: string
  onChange?: (event: ChangeEvent<HTMLSelectElement>) => void
}) => ReactElement

const TableControl = TableView as unknown as (props: {
  columns: Array<{ title: string, sortable?: boolean, showSortIcon?: boolean }>
  rows: string[][]
  rowFontSize?: number
  headerFontSize?: number
}) => ReactElement

const SliderControl = SliderBar as unknown as (props: {
  min: number
  max: number
  defaultValue: number
  width?: string
  onChange?: (event: ChangeEvent<HTMLInputElement>) => void
}) => ReactElement

function DashboardView({
  dashboard,
  logs,
  busy = false,
  onUpdateUrl,
  onAutoConfig,
  onLoadConfig,
  onSaveConfig,
  onOpenRuntime,
  onTargetChange,
  onThreadsChange,
  onRandomIpChange,
  onProxySourceChange,
  onRun,
  onCancelRun,
}: DashboardViewProps) {
  const questionRows = dashboard.questionRows.map((row) => [
    String(row.index),
    row.type,
    row.dimension || '-',
    row.strategy || '-',
  ])
  const sessionRows = dashboard.sessionRows.map((row) => [row.thread, row.status, `${row.progress}%`])

  return (
    <section className="page dashboard-page">
      <div className="dashboard-scroll">
        <section className="surface survey-entry">
          <div className="icon-tile">
            <Button icon={<QrCode size={18} />} tooltip="二维码" />
          </div>
          <div className="entry-main">
            <div className="entry-row">
              <InputText
                value={dashboard.surveyUrl}
                placeholder="在此拖入/粘贴问卷二维码图片或输入问卷链接"
                clearButton
                width="100%"
                onChange={(event: ChangeEvent<HTMLInputElement>) => onUpdateUrl(event.target.value)}
                onClearButtonClick={() => onUpdateUrl('')}
              />
              <ButtonGroup>
                <Button value="配置列表" icon={<List size={16} />} onClick={onLoadConfig} />
                <Button value="载入配置" icon={<FilePlus2 size={16} />} onClick={onLoadConfig} />
                <Button value="保存配置" icon={<Save size={16} />} onClick={onSaveConfig} />
              </ButtonGroup>
            </div>
            <Button
              type="primary"
              value="自动配置问卷"
              icon={<Play size={16} />}
              disabled={busy || !dashboard.surveyUrl}
              isLoading={busy}
              onClick={onAutoConfig}
            />
          </div>
        </section>

        <section className="surface quick-panel">
          <div className="section-heading">
            <h1>快捷设置</h1>
            <span>{dashboard.platformLabel}</span>
          </div>

          <div className="quick-grid">
            <div className="quick-fields">
              <div className="control-line">
                <label>目标份数</label>
                <InputText
                  value={String(dashboard.targetCount)}
                  width="8rem"
                  onChange={(event: ChangeEvent<HTMLInputElement>) => onTargetChange(Number(event.target.value))}
                />
                <label>并发数</label>
                <SliderControl
                  key={`threads-${dashboard.threadCount}`}
                  min={1}
                  max={32}
                  defaultValue={Math.max(1, Math.min(dashboard.threadCount, 32))}
                  width="10rem"
                  onChange={(event: ChangeEvent<HTMLInputElement>) => onThreadsChange(Number(event.target.value))}
                />
                <strong className="inline-value">{Math.max(1, Math.min(dashboard.threadCount, 32))}</strong>
              </div>

              <div className="control-line">
                <label>随机 IP</label>
                <Switch
                  key={`random-ip-${dashboard.randomIpEnabled}`}
                  label
                  labelOn="开"
                  labelOff="关"
                  defaultChecked={dashboard.randomIpEnabled}
                  onChange={() => onRandomIpChange(!dashboard.randomIpEnabled)}
                />
                <label>代理源</label>
                <SelectControl
                  data={[
                    { label: '默认', value: '默认' },
                    { label: '限时福利', value: '限时福利' },
                    { label: '自定义', value: '自定义' },
                  ]}
                  value={dashboard.proxySource}
                  onChange={(event) => onProxySourceChange(event.target.value)}
                />
              </div>

              <div className="runtime-link">
                <div className="runtime-icon">
                  <SlidersHorizontal size={20} />
                </div>
                <div>
                  <strong>运行参数</strong>
                  <span>更多参数在独立页调整</span>
                </div>
                <Button value="打开" onClick={onOpenRuntime} />
              </div>
            </div>

            {dashboard.randomIpEnabled ? (
              <aside className="quota-panel">
                <span>剩余随机 IP 额度</span>
                <strong>{dashboard.randomIpQuotaLabel}</strong>
                <small>{dashboard.randomIpStatus}</small>
                <div>可用 {dashboard.proxyAvailable ?? 0} / 占用 {dashboard.proxyInUse ?? 0}</div>
              </aside>
            ) : null}
          </div>
        </section>

        <section className="metrics-strip">
          {dashboard.metrics.map((metric) => (
            <div key={metric.label} className={`metric-chip ${metric.tone ? `metric-${metric.tone}` : ''}`}>
              <span>{metric.label}</span>
              <strong>{metric.value}</strong>
            </div>
          ))}
        </section>

        <section className="surface table-panel">
          <div className="section-heading">
            <h2>已配置的题目</h2>
            <span>{dashboard.questionRows.length} 题</span>
          </div>
          <div className="table-actions">
            <Button value="新增题目" icon={<FilePlus2 size={15} />} disabled />
            <Button value="编辑选中" icon={<Brush size={15} />} disabled />
            <Button value="删除选中" icon={<Trash2 size={15} />} disabled />
            <Button value="清空所有" icon={<Brush size={15} />} disabled />
          </div>
          <TableControl
            columns={[
              { title: '序号', showSortIcon: false },
              { title: '类型', showSortIcon: false },
              { title: '维度', showSortIcon: false },
              { title: '策略', showSortIcon: false },
            ]}
            rows={questionRows}
            rowFontSize={13}
            headerFontSize={13}
          />
        </section>

        {sessionRows.length ? (
          <section className="surface table-panel">
            <div className="section-heading">
              <h2>会话进度</h2>
              <span>{sessionRows.length} 路</span>
            </div>
            <TableControl
              columns={[
                { title: '线程', showSortIcon: false },
                { title: '状态', showSortIcon: false },
                { title: '进度', showSortIcon: false },
              ]}
              rows={sessionRows}
              rowFontSize={13}
              headerFontSize={13}
            />
          </section>
        ) : null}

        {logs.length ? (
          <section className="surface compact-log">
            {logs.slice(0, 3).map((line) => <code key={line}>{line}</code>)}
          </section>
        ) : null}
      </div>

      <footer className="run-footer">
        <strong>{dashboard.statusText}</strong>
        <ProgressBar setProgress={dashboard.progressPercent} width="100%" />
        <span>{dashboard.progressPercent}%</span>
        <Button
          type="primary"
          value="开始执行"
          icon={<Play size={16} />}
          disabled={busy || !dashboard.surveyUrl}
          onClick={onRun}
        />
        <Button
          value="停止"
          icon={<Square size={14} />}
          disabled={!busy}
          onClick={onCancelRun}
        />
      </footer>
    </section>
  )
}

export default DashboardView

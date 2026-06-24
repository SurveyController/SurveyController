interface LogsViewProps {
  logs: string[]
}

function LogsView({ logs }: LogsViewProps) {
  return (
    <section className="page scroll-page">
      <section className="surface log-panel">
        <div className="section-heading">
          <h2>日志</h2>
          <span>{logs.length}</span>
        </div>
        <div className="log-lines">
          {logs.map((line) => <code key={line}>{line}</code>)}
        </div>
      </section>
    </section>
  )
}

export default LogsView

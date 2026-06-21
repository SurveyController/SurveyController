<script lang="ts">
  import FluentSegmentedControl from '../components/FluentSegmentedControl.svelte'
  import PageHeader from '../components/PageHeader.svelte'
  import { shellState } from '../shell-state.svelte'

  let tab = $state<'rules' | 'dimensions'>('rules')
</script>

<section class="page strategy-page">
  <PageHeader
    eyebrow="Rules"
    title="题目策略"
    description="保留旧版的分段切换：条件规则和维度分组。"
  />

  <div class="strategy-switch">
    <FluentSegmentedControl
      value={tab}
      options={[
        { value: 'rules', label: '条件规则' },
        { value: 'dimensions', label: '维度分组' },
      ]}
    />
  </div>

  {#if tab === 'rules'}
    <article class="panel">
      <div class="panel__title">
        <h3>条件规则</h3>
        <span>{shellState.payload.strategyRules.length} 条</span>
      </div>
      <div class="rule-list">
        {#each shellState.payload.strategyRules as rule, index (`${rule.condition}-${index}`)}
          <div class="rule-card">
            <strong>{rule.condition}</strong>
            <p>{rule.action}</p>
            <span>{rule.target}</span>
          </div>
        {/each}
      </div>
    </article>
  {:else}
    <article class="panel">
      <div class="panel__title">
        <h3>维度分组</h3>
        <span>{shellState.payload.dimensionGroups.length} 组</span>
      </div>
      <div class="dimension-cloud">
        {#each shellState.payload.dimensionGroups as group (group)}
          <div class="dimension-pill">{group}</div>
        {/each}
      </div>
    </article>
  {/if}
</section>

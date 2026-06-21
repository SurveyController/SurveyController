<script lang="ts">
  import PageHeader from '../components/PageHeader.svelte'
  import SettingCard from '../components/SettingCard.svelte'
  import { shellState } from '../shell-state.svelte'
</script>

<section class="page runtime-page">
  <PageHeader
    eyebrow="Parameters"
    title="运行参数"
    description="按旧版设置卡分组复刻。这里先放结构，后面接绑定和持久化。"
  />

  <div class="settings-stack">
    {#each shellState.payload.runtimeGroups as group (group.title)}
      <article class="settings-group">
        <div class="settings-group__header">
          <h3>{group.title}</h3>
        </div>
        <div class="settings-group__body">
          {#each group.fields as field (field.id)}
            <SettingCard {field} />
          {/each}
        </div>
      </article>
    {/each}
  </div>
</section>

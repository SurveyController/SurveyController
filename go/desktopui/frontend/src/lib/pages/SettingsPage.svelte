<script lang="ts">
  import PageHeader from '../components/PageHeader.svelte'
  import SettingCard from '../components/SettingCard.svelte'
  import { shellState } from '../shell-state.svelte'
</script>

<section class="page settings-page">
  <PageHeader
    eyebrow="Preferences"
    title="设置"
    description="按旧版 SettingCardGroup 拆块，先保留信息层级和视觉结构。"
  />

  <div class="settings-stack">
    {#each shellState.payload.settingsGroups as group (group.title)}
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
